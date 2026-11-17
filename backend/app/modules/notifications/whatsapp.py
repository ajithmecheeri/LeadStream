"""WhatsApp through Meta's WhatsApp Business (Cloud) API: the official API only, never WhatsApp Web automation.

Messages BrewMyJob starts must use templates Meta has approved (docs/plan-m6.md lists the two to create):
- WHATSAPP_JOB_TEMPLATE (utility): title, company, score and the link to the job in BrewMyJob, in that order
  (the exact body is in docs/plan-m6.md; Meta wants variables in order and not at the very end);
- WHATSAPP_CODE_TEMPLATE (authentication, with a copy-code button): the one-time code that verifies a number.

Without WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN nothing is sent: the message is written to the worker
log and marked "logged", so the whole flow can be tried locally.
"""

import logging
import re
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

log = logging.getLogger("fitfirst.whatsapp")

GRAPH = "https://graph.facebook.com"


class WhatsAppError(Exception):
    """Meta refused the message. `permanent`: retrying won't help (bad number, template missing)."""

    def __init__(self, message: str, permanent: bool):
        super().__init__(message)
        self.permanent = permanent


@dataclass(frozen=True)
class Sent:
    provider_id: str | None  # None: logged, not sent (no keys)


def configured() -> bool:
    s = get_settings()
    return bool(s.whatsapp_phone_number_id and s.whatsapp_access_token)


def normalise_number(raw: str) -> str | None:
    """Digits with the country code, as WhatsApp wants them. A 10-digit Indian mobile gets +91."""
    digits = re.sub(r"\D", "", raw or "")
    if raw.strip().startswith("00"):
        digits = digits[2:]
    digits = digits.lstrip("0") if len(digits) == 11 and digits.startswith("0") else digits
    if len(digits) == 10 and digits[0] in "6789":
        digits = "91" + digits
    return digits if re.fullmatch(r"[1-9]\d{9,14}", digits) else None


def masked(number: str) -> str:
    return f"+{number[:-10]} ••••• {number[-5:]}" if len(number) > 10 else "•••••" + number[-5:]


def _template(name: str, params: list[str], code_button: str | None = None) -> dict:
    components: list[dict] = [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]
    if code_button is not None:  # an authentication template's copy-code button carries the code too
        components.append(
            {
                "type": "button",
                "sub_type": "url",
                "index": "0",
                "parameters": [{"type": "text", "text": code_button}],
            }
        )
    return {
        "name": name,
        "language": {"code": get_settings().whatsapp_template_language},
        "components": components,
    }


async def _send(to: str, template: dict, preview: str, http: httpx.AsyncClient | None = None) -> Sent:
    if not configured():
        log.info("WhatsApp (not configured, not sent) to %s: %s", masked(to), preview)
        return Sent(None)
    s = get_settings()
    url = f"{GRAPH}/{s.whatsapp_api_version}/{s.whatsapp_phone_number_id}/messages"
    payload = {"messaging_product": "whatsapp", "to": to, "type": "template", "template": template}
    headers = {"Authorization": f"Bearer {s.whatsapp_access_token}"}
    own = http is None
    http = http or httpx.AsyncClient(timeout=20)
    try:
        r = await http.post(url, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise WhatsAppError(f"WhatsApp unreachable: {e.__class__.__name__}", permanent=False) from e
    finally:
        if own:
            await http.aclose()
    if r.status_code >= 400:
        err = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get(
            "error"
        ) or {}
        message = err.get("message") or f"HTTP {r.status_code}"
        # 4xx other than rate limits won't change on a retry (bad number, unknown template, token).
        raise WhatsAppError(f"WhatsApp: {message}", permanent=r.status_code < 500 and r.status_code != 429)
    messages = r.json().get("messages") or [{}]
    return Sent(messages[0].get("id"))


async def send_job(to: str, title: str, company: str, score: int, link: str, **kw) -> Sent:
    params = [title[:200], company[:100] or "a company", str(score), link]
    preview = f"Top match, {score}%: {title} at {company}. {link}"
    return await _send(to, _template(get_settings().whatsapp_job_template, params), preview, **kw)


async def send_code(to: str, code: str, **kw) -> Sent:
    template = _template(get_settings().whatsapp_code_template, [code], code_button=code)
    return await _send(to, template, f"verification code {code}", **kw)
