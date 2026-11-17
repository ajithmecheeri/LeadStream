"""The one place AI is called from: Claude for prompts, Voyage for embeddings.

Every call is logged in llm_calls (tokens, cost, latency, success) and capped per user per day. Nothing here
raises on a provider problem: `run` and `embed` return None, and the caller uses its rule-based fallback.
That is also what happens when there is no API key, so the app works fully without one.

Routing is by prompt name (ROUTES), so a single task can later move to a self-hosted model (an
OpenAI-compatible endpoint) without touching the code that asks for it.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.llm.models import LlmCall

log = logging.getLogger("fitfirst.llm")

PROMPTS = Path(__file__).resolve().parents[3] / "prompts"

# US$ per million tokens (input, output), from docs/LLD.md.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "voyage-4-lite": (0.02, 0.0),
}

# prompt name -> (provider, model, prompt version)
ROUTES: dict[str, tuple[str, str, str]] = {
    "resume_extract": ("anthropic", "claude-haiku-5-5", "v1"),
}


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    async def complete(self, model: str, system: str, user: str, max_tokens: int) -> Completion: ...


class Embedder(Protocol):
    model: str

    async def embed(self, texts: list[str], input_type: str) -> tuple[list[list[float]], int]: ...


class AnthropicProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def complete(self, model: str, system: str, user: str, max_tokens: int) -> Completion:
        async with httpx.AsyncClient(timeout=60) as http:
            r = await http.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
        r.raise_for_status()
        body = r.json()
        text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
        usage = body.get("usage", {})
        return Completion(text, usage.get("input_tokens", 0), usage.get("output_tokens", 0))


class VoyageEmbedder:
    BATCH = 128
    # Keys without a payment method allow 3 requests and 10K tokens a minute: keep each request under that, and
    # on 429 wait for the next minute and try again (a full re-score of a few hundred jobs then takes minutes).
    MAX_BATCH_TOKENS = 8_000
    RETRIES_429 = 6
    WAIT_429 = 21

    def __init__(self, api_key: str, model: str, dims: int):
        self.api_key, self.model, self.dims = api_key, model, dims

    @classmethod
    def batches(cls, texts: list[str]) -> list[list[str]]:
        """Consecutive batches of at most BATCH texts and about MAX_BATCH_TOKENS tokens (3 characters a token,
        on the safe side)."""
        out: list[list[str]] = []
        size = 0
        for t in texts:
            est = len(t) // 3 + 1
            if not out or len(out[-1]) >= cls.BATCH or size + est > cls.MAX_BATCH_TOKENS:
                out.append([])
                size = 0
            out[-1].append(t)
            size += est
        return out

    async def embed(self, texts: list[str], input_type: str) -> tuple[list[list[float]], int]:
        vectors: list[list[float]] = []
        tokens = 0
        async with httpx.AsyncClient(timeout=60) as http:
            for batch in self.batches(texts):
                body = {
                    "input": batch,
                    "model": self.model,
                    "input_type": input_type,
                    "output_dimension": self.dims,
                }
                headers = {"Authorization": f"Bearer {self.api_key}"}
                r = await http.post("https://api.voyageai.com/v1/embeddings", headers=headers, json=body)
                for _ in range(self.RETRIES_429):
                    if r.status_code != 429:
                        break
                    await asyncio.sleep(self.WAIT_429)
                    r = await http.post("https://api.voyageai.com/v1/embeddings", headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
                vectors += [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
                tokens += data.get("usage", {}).get("total_tokens", 0)
        return vectors, tokens


# Tests swap these in; None means "use the configured provider".
_provider_override: dict[str, Provider] = {}
_embedder_override: list[Embedder] = []


def use_provider(name: str, provider: Provider | None) -> None:
    if provider is None:
        _provider_override.pop(name, None)
    else:
        _provider_override[name] = provider


def use_embedder(embedder: Embedder | None) -> None:
    _embedder_override.clear()
    if embedder is not None:
        _embedder_override.append(embedder)


def _provider(name: str) -> Provider | None:
    if name in _provider_override:
        return _provider_override[name]
    s = get_settings()
    if name == "anthropic" and s.anthropic_api_key:
        return AnthropicProvider(s.anthropic_api_key)
    return None


def embedder() -> Embedder | None:
    if _embedder_override:
        return _embedder_override[0]
    s = get_settings()
    return VoyageEmbedder(s.voyage_api_key, s.voyage_model, s.embedding_dims) if s.voyage_api_key else None


def _cost(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    p_in, p_out = PRICES.get(model, (0.0, 0.0))
    return Decimal(str(round((tokens_in * p_in + tokens_out * p_out) / 1_000_000, 6)))


async def _over_cap(db: AsyncSession, user_id: UUID) -> bool:
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    spent = await db.scalar(
        select(func.coalesce(func.sum(LlmCall.cost_usd), 0)).where(
            LlmCall.user_id == user_id, LlmCall.created_at >= today
        )
    )
    if float(spent or 0) >= get_settings().llm_daily_cost_cap_usd:
        log.warning("user %s reached the daily AI cost cap; using rules", user_id)
        return True
    return False


def _record(db: AsyncSession, user_id: UUID, **kw) -> None:
    db.add(LlmCall(user_id=user_id, **kw))


def load_prompt(name: str, version: str) -> str:
    return (PROMPTS / name / f"{version}.md").read_text(encoding="utf-8")


def _json_block(text: str) -> str:
    """The JSON object in a reply, with or without a ``` fence around it."""
    m = re.search(r"\{.*\}", text, re.S)
    return m.group(0) if m else text


async def run[T: BaseModel](
    db: AsyncSession, user_id: UUID, prompt: str, schema: type[T], inputs: dict, max_tokens: int = 1500
) -> T | None:
    """Run a versioned prompt and validate the reply against `schema`. None means: use the fallback."""
    provider_name, model, version = ROUTES[prompt]
    provider = _provider(provider_name)
    if provider is None or await _over_cap(db, user_id):
        return None
    system = load_prompt(prompt, version)
    user = json.dumps(inputs, ensure_ascii=False, default=str)
    for attempt in (1, 2):  # one retry when the reply doesn't validate
        started = time.monotonic()
        try:
            c = await provider.complete(model, system, user, max_tokens)
        except Exception as e:
            _record(
                db,
                user_id,
                provider=provider_name,
                model=model,
                prompt=prompt,
                prompt_version=version,
                ok=False,
                error=f"{type(e).__name__}: {e}"[:500],
            )
            log.warning("%s failed: %s", prompt, e)
            return None
        record = dict(
            provider=provider_name,
            model=model,
            prompt=prompt,
            prompt_version=version,
            input_tokens=c.input_tokens,
            output_tokens=c.output_tokens,
            cost_usd=_cost(model, c.input_tokens, c.output_tokens),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        try:
            result = schema.model_validate_json(_json_block(c.text))
        except ValidationError as e:
            _record(db, user_id, **record, ok=False, error=f"invalid output (attempt {attempt}): {e}"[:500])
            continue
        _record(db, user_id, **record, ok=True, error=None)
        return result
    return None


async def embed(
    db: AsyncSession, user_id: UUID, texts: list[str], purpose: str, input_type: str = "document"
) -> list[list[float]] | None:
    """Embeddings for `texts`, in order. None when there is no key, the cap is reached or Voyage fails."""
    e = embedder()
    if e is None or not texts or await _over_cap(db, user_id):
        return None
    started = time.monotonic()
    try:
        vectors, tokens = await e.embed(texts, input_type)
    except Exception as err:
        _record(
            db,
            user_id,
            provider="voyage",
            model=e.model,
            prompt=f"embed:{purpose}",
            ok=False,
            error=f"{type(err).__name__}: {err}"[:500],
        )
        log.warning("embedding failed (%s): %s", purpose, err)
        return None
    _record(
        db,
        user_id,
        provider="voyage",
        model=e.model,
        prompt=f"embed:{purpose}",
        input_tokens=tokens,
        cost_usd=_cost(e.model, tokens, 0),
        latency_ms=int((time.monotonic() - started) * 1000),
        ok=True,
    )
    return vectors
