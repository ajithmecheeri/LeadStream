"""Send a saved alert email to the running API, exactly as the Cloudflare Email Worker would.

    make inbound FILE=TestFiles/raw/alert.eml                 # to the demo user
    make inbound FILE=… TO=alerts-xxxx@in.fitfirst.local      # to another user's forwarding address
    make inbound FILE=… AGAIN=1                               # resend: a fresh Message-ID, so not a duplicate

DKIM is reported as passing for the email's From domain, as Cloudflare does for a genuine alert. The
request is signed with INBOUND_HMAC_SECRET from .env, so the API must have the same value.
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.modules.catalog.parsers.base import sender  # noqa: E402
from app.modules.catalog.parsers.registry import load  # noqa: E402
from app.modules.ingestion.service import GOOGLE_FORWARDING, sign  # noqa: E402

API = os.environ.get("API_URL", "http://localhost:8000")


def _call(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers or {})
    req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except urllib.error.URLError as e:
        sys.exit(f"Can't reach the API at {API} ({e.reason}). Start it with `make dev` or `make up`.")


def demo_address() -> str:
    email = os.environ.get("DEMO_EMAIL", "demo@example.com")
    password = os.environ.get("DEMO_PASSWORD", "FitFirst-demo-2026")
    status, body = _call("POST", "/api/v1/auth/login", {"email": email, "password": password})
    if status != 200:
        sys.exit(f"Couldn't sign in as {email} to find its forwarding address: {body}. Pass TO=… instead.")
    _, me = _call("GET", "/api/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    return me["forwarding_address"]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file", type=Path)
    p.add_argument("--to", help="forwarding address (default: the demo user's)")
    p.add_argument("--again", action="store_true", help="send with a fresh Message-ID")
    args = p.parse_args()

    secret = get_settings().inbound_hmac_secret
    if not secret:
        sys.exit("INBOUND_HMAC_SECRET is empty. Add it to .env (see .env.example) and restart the API.")
    raw = args.file.read_bytes()
    from_addr = sender(load(raw))
    dkim_domain = "google.com" if from_addr == GOOGLE_FORWARDING else from_addr.rpartition("@")[2]
    payload = {
        "recipient": args.to or demo_address(),
        "envelope_from": from_addr,
        "dkim": [{"domain": dkim_domain, "result": "pass"}],
        "raw_mime_base64": base64.b64encode(raw).decode(),
    }
    if args.again:
        payload["message_id"] = f"<resend-{uuid.uuid4().hex}@fitfirst.local>"

    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    req = urllib.request.Request(
        API + "/internal/inbound",
        data=body,
        method="POST",
        headers={
            "content-type": "application/json",
            "x-timestamp": ts,
            "x-signature": sign(secret, ts, body),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, result = r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        status, result = e.code, json.loads(e.read() or b"{}")
    except urllib.error.URLError as e:
        sys.exit(f"Can't reach the API at {API} ({e.reason}). Start it with `make dev` or `make up`.")

    print(f"{args.file.name} → {payload['recipient']}: HTTP {status}")
    print(json.dumps(result, indent=2))
    if result.get("accepted"):
        print("Queued for parsing. See it in the API docs: GET /api/v1/inbox/messages")
    elif result.get("reason") == "duplicate":
        print("Already received. Add AGAIN=1 to send it as a new email.")


if __name__ == "__main__":
    main()
