// Posting an email to the API's /internal/inbound, signed the way backend/app/modules/ingestion/service.py
// checks it: X-Signature = "sha256=" + HMAC-SHA256(secret, "<X-Timestamp>.<body>").

import type { DkimResult } from "./auth";

export interface InboundPayload {
  recipient: string;
  envelope_from: string;
  message_id: string | null;
  received_at: string;
  dkim: DkimResult[];
  raw_mime_base64: string;
}

/** done: the API decided (accepted or not; retrying won't change it). retry: try again later. */
export type Outcome = { kind: "done"; accepted: boolean; reason: string | null } | { kind: "retry"; why: string };

export async function sign(secret: string, timestamp: string, body: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
  ]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(`${timestamp}.${body}`)));
  return "sha256=" + Array.from(mac, (b) => b.toString(16).padStart(2, "0")).join("");
}

export async function deliver(
  payload: InboundPayload,
  apiUrl: string,
  secret: string,
  fetchFn: typeof fetch = fetch,
): Promise<Outcome> {
  const body = JSON.stringify(payload);
  const timestamp = Math.floor(Date.now() / 1000).toString();
  let res: Response;
  try {
    res = await fetchFn(apiUrl.replace(/\/$/, "") + "/internal/inbound", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-timestamp": timestamp,
        "x-signature": await sign(secret, timestamp, body),
      },
      body,
    });
  } catch (e) {
    return { kind: "retry", why: `unreachable: ${e instanceof Error ? e.message : String(e)}` };
  }
  if (res.ok) {
    const result = (await res.json().catch(() => ({}))) as { accepted?: boolean; reason?: string | null };
    return { kind: "done", accepted: result.accepted === true, reason: result.reason ?? null };
  }
  // The API read the request and refused it: sending it again would be refused again.
  if (res.status === 413 || res.status === 422) return { kind: "done", accepted: false, reason: `http_${res.status}` };
  // 401 (secrets differ), 503 (inbound not configured), 5xx, or the tunnel is down (502/530): fixable, so retry.
  return { kind: "retry", why: `http_${res.status}` };
}

export function base64(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}
