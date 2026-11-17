// Cloudflare Email Worker: Email Routing sends every message for <INBOUND_DOMAIN> here.
//
// Each email for alerts-<token>@<INBOUND_DOMAIN> goes to the API with Cloudflare's DKIM results; the API decides
// whether the sender is allowed (LinkedIn, Naukri, Gmail's forwarding confirmation) and whose address it is.
// When the API can't be reached the email waits in KV (OUTBOX) and the cron retries it for up to 7 days.

import { dkimResults, headerFields } from "./auth";
import { base64, deliver, type InboundPayload } from "./deliver";

export interface Env {
  API_URL: string;
  INBOUND_DOMAIN: string;
  INBOUND_HMAC_SECRET: string;
  OUTBOX: KVNamespace;
}

export const MAX_BYTES = 5 * 1024 * 1024; // the API's inbound_max_bytes
const KEEP_SECONDS = 7 * 24 * 3600;
const RETRY_BATCH = 50;

export function isAlertAddress(address: string, inboundDomain: string): boolean {
  const m = /^alerts-[A-Za-z0-9_-]+@(.+)$/.exec(address.trim());
  return !!m && m[1]!.toLowerCase() === inboundDomain.toLowerCase();
}

/** The recipient without its token, for logs (the token is what lets mail reach a user). */
function masked(address: string): string {
  return address.replace(/^(alerts-[^@]{0,4})[^@]*@/, "$1…@");
}

function log(event: string, details: Record<string, unknown>): void {
  console.log(JSON.stringify({ event, ...details }));
}

export default {
  async email(message: ForwardableEmailMessage, env: Env, ctx: ExecutionContext): Promise<void> {
    if (!isAlertAddress(message.to, env.INBOUND_DOMAIN)) {
      message.setReject("Unknown address");
      return;
    }
    if (message.rawSize > MAX_BYTES) {
      message.setReject("Message too large");
      return;
    }
    const raw = new Uint8Array(await new Response(message.raw).arrayBuffer());
    const dkim = dkimResults(headerFields(raw));
    const payload: InboundPayload = {
      recipient: message.to,
      envelope_from: message.from,
      message_id: message.headers.get("message-id"),
      received_at: new Date().toISOString(),
      dkim,
      raw_mime_base64: base64(raw),
    };
    const outcome = await deliver(payload, env.API_URL, env.INBOUND_HMAC_SECRET);
    log("inbound", { to: masked(message.to), from: message.headers.get("from"), dkim, outcome });
    if (outcome.kind === "retry") {
      const key = `pending:${payload.received_at}:${crypto.randomUUID()}`;
      ctx.waitUntil(env.OUTBOX.put(key, JSON.stringify(payload), { expirationTtl: KEEP_SECONDS }));
      return;
    }
    if (outcome.reason === "unknown_recipient") {
      // Bounce, so a mistyped forwarding address in Gmail fails its confirmation instead of vanishing.
      message.setReject("Unknown BrewMyJob forwarding address");
    }
  },

  async scheduled(_controller: ScheduledController, env: Env, _ctx: ExecutionContext): Promise<void> {
    const { keys } = await env.OUTBOX.list({ prefix: "pending:", limit: RETRY_BATCH });
    for (const { name } of keys) {
      const stored = await env.OUTBOX.get(name);
      if (stored === null) continue;
      const payload = JSON.parse(stored) as InboundPayload;
      const outcome = await deliver(payload, env.API_URL, env.INBOUND_HMAC_SECRET);
      log("retry", { to: masked(payload.recipient), outcome });
      if (outcome.kind === "retry") break; // still unreachable: leave the rest for the next run
      await env.OUTBOX.delete(name);
    }
  },
} satisfies ExportedHandler<Env>;
