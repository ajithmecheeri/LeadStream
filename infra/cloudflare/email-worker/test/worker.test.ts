import { afterEach, describe, expect, it, vi } from "vitest";
import { dkimResults, headerFields } from "../src/auth";
import { base64, deliver, sign, type InboundPayload } from "../src/deliver";
import worker, { isAlertAddress, MAX_BYTES, type Env } from "../src/index";

const enc = new TextEncoder();
const CF = "ARC-Authentication-Results: i=2; mx.cloudflare.net;\r\n dkim=pass header.d=linkedin.com header.s=proddkim1024 header.b=abc;\r\n spf=pass";

function email(headers: string[], body = "Hello"): Uint8Array {
  return enc.encode(headers.join("\r\n") + "\r\n\r\n" + body);
}

const ALERT = email([
  CF,
  "ARC-Authentication-Results: i=1; mx.google.com; dkim=pass header.d=linkedin.com",
  "From: LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
  "Message-ID: <alert-1@linkedin.com>",
  "Subject: Vice President: Acme",
]);

describe("signature", () => {
  it("matches what the API computes (backend/app/modules/ingestion/service.py sign)", async () => {
    const body = '{"recipient":"alerts-abc@in.example.com"}';
    expect(await sign("test-secret", "1700000000", body)).toBe(
      "sha256=ffdf7de2afe7ce622762729a03d876c8dbab8995f57c17b68b41d56fcd587c3f",
    );
  });
});

describe("DKIM results", () => {
  it("reads Cloudflare's topmost header, unfolded", () => {
    expect(dkimResults(headerFields(ALERT))).toEqual([{ domain: "linkedin.com", result: "pass" }]);
  });

  it("also reads a plain Authentication-Results and header.i", () => {
    const raw = email(["Authentication-Results: mx.cloudflare.net; dkim=fail header.i=@naukri.com", "From: x@naukri.com"]);
    expect(dkimResults(headerFields(raw))).toEqual([{ domain: "naukri.com", result: "fail" }]);
  });

  it("ignores a forged result further down", () => {
    const raw = email([
      "ARC-Authentication-Results: i=1; mx.cloudflare.net; dkim=none",
      "Authentication-Results: mx.cloudflare.net; dkim=pass header.d=linkedin.com",
    ]);
    expect(dkimResults(headerFields(raw))).toEqual([]);
  });

  it("trusts nothing when the topmost header isn't Cloudflare's", () => {
    const raw = email(["Authentication-Results: mx.attacker.example; dkim=pass header.d=linkedin.com"]);
    expect(dkimResults(headerFields(raw))).toEqual([]);
  });

  it("ignores the body", () => {
    const raw = email(["From: a@b.c"], "Authentication-Results: mx.cloudflare.net; dkim=pass header.d=linkedin.com");
    expect(dkimResults(headerFields(raw))).toEqual([]);
  });
});

describe("addresses", () => {
  it("accepts only alerts-<token> at the inbound domain", () => {
    expect(isAlertAddress("alerts-Ab_9-x@in.brewmyjob.com", "in.brewmyjob.com")).toBe(true);
    expect(isAlertAddress("alerts-abc@IN.BREWMYJOB.COM", "in.brewmyjob.com")).toBe(true);
    expect(isAlertAddress("hello@in.brewmyjob.com", "in.brewmyjob.com")).toBe(false);
    expect(isAlertAddress("alerts-abc@brewmyjob.com", "in.brewmyjob.com")).toBe(false);
    expect(isAlertAddress("alerts-a.b@in.brewmyjob.com", "in.brewmyjob.com")).toBe(false);
  });
});

describe("deliver", () => {
  const payload: InboundPayload = {
    recipient: "alerts-abc@in.brewmyjob.com",
    envelope_from: "me@gmail.com",
    message_id: "<1@x>",
    received_at: "2026-11-03T00:00:00.000Z",
    dkim: [],
    raw_mime_base64: base64(ALERT),
  };

  it("signs the exact body it sends", async () => {
    const fetchFn = vi.fn(async () => Response.json({ accepted: true }));
    const outcome = await deliver(payload, "https://inbound.example.com/", "s3cret", fetchFn as typeof fetch);
    expect(outcome).toEqual({ kind: "done", accepted: true, reason: null });
    const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://inbound.example.com/internal/inbound");
    const headers = init.headers as Record<string, string>;
    expect(headers["x-signature"]).toBe(await sign("s3cret", headers["x-timestamp"]!, init.body as string));
    expect(JSON.parse(init.body as string)).toEqual(payload);
  });

  it.each([
    [401, "retry"],
    [502, "retry"],
    [503, "retry"],
    [530, "retry"],
    [413, "done"],
    [422, "done"],
  ])("HTTP %i → %s", async (status, kind) => {
    const fetchFn = async () => new Response("{}", { status });
    expect((await deliver(payload, "https://x", "s", fetchFn as typeof fetch)).kind).toBe(kind);
  });

  it("retries when the API can't be reached", async () => {
    const fetchFn = async () => {
      throw new Error("connection refused");
    };
    expect((await deliver(payload, "https://x", "s", fetchFn as typeof fetch)).kind).toBe("retry");
  });

  it("base64 survives large binary input", () => {
    const bytes = new Uint8Array(100_000).map((_, i) => i % 256);
    expect(Uint8Array.from(atob(base64(bytes)), (c) => c.charCodeAt(0))).toEqual(bytes);
  });
});

// --- The handlers, with a fake Email Routing message and KV ----------------------------------------------

function fakeKv() {
  const store = new Map<string, string>();
  return {
    store,
    put: vi.fn(async (k: string, v: string) => void store.set(k, v)),
    get: vi.fn(async (k: string) => store.get(k) ?? null),
    delete: vi.fn(async (k: string) => void store.delete(k)),
    list: vi.fn(async ({ prefix }: { prefix: string }) => ({
      keys: [...store.keys()].filter((k) => k.startsWith(prefix)).sort().map((name) => ({ name })),
    })),
  };
}

function setup(to = "alerts-abc123@in.brewmyjob.com", raw = ALERT, rawSize = raw.length) {
  const kv = fakeKv();
  const env = { API_URL: "https://inbound.example.com", INBOUND_DOMAIN: "in.brewmyjob.com", INBOUND_HMAC_SECRET: "s", OUTBOX: kv } as unknown as Env;
  const waits: Promise<unknown>[] = [];
  const ctx = { waitUntil: (p: Promise<unknown>) => waits.push(p) } as unknown as ExecutionContext;
  const message = {
    to,
    from: "me@gmail.com",
    rawSize,
    raw: new Response(raw).body,
    headers: new Headers({ "message-id": "<alert-1@linkedin.com>" }),
    setReject: vi.fn(),
  } as unknown as ForwardableEmailMessage & { setReject: ReturnType<typeof vi.fn> };
  return { kv, env, ctx, message, waits };
}

function mockApi(...responses: (Response | Error)[]) {
  const fn = vi.fn(async () => {
    const next = responses.shift() ?? Response.json({ accepted: true });
    if (next instanceof Error) throw next;
    return next;
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("email handler", () => {
  it("posts an alert with Cloudflare's DKIM results", async () => {
    const api = mockApi(Response.json({ accepted: true }));
    const { env, ctx, message, kv } = setup();
    await worker.email(message, env, ctx);
    const sent = JSON.parse((api.mock.calls[0] as unknown as [string, RequestInit])[1].body as string);
    expect(sent.recipient).toBe("alerts-abc123@in.brewmyjob.com");
    expect(sent.message_id).toBe("<alert-1@linkedin.com>");
    expect(sent.dkim).toEqual([{ domain: "linkedin.com", result: "pass" }]);
    expect(message.setReject).not.toHaveBeenCalled();
    expect(kv.put).not.toHaveBeenCalled();
  });

  it("bounces other addresses and oversized mail without calling the API", async () => {
    const api = mockApi();
    const a = setup("hello@in.brewmyjob.com");
    await worker.email(a.message, a.env, a.ctx);
    expect(a.message.setReject).toHaveBeenCalledWith("Unknown address");
    const b = setup(undefined, ALERT, MAX_BYTES + 1);
    await worker.email(b.message, b.env, b.ctx);
    expect(b.message.setReject).toHaveBeenCalledWith("Message too large");
    expect(api).not.toHaveBeenCalled();
  });

  it("bounces an address the API doesn't know, and quietly drops a sender it doesn't allow", async () => {
    mockApi(Response.json({ accepted: false, reason: "unknown_recipient" }));
    const a = setup();
    await worker.email(a.message, a.env, a.ctx);
    expect(a.message.setReject).toHaveBeenCalledWith("Unknown BrewMyJob forwarding address");

    mockApi(Response.json({ accepted: false, reason: "sender_not_allowed" }));
    const b = setup();
    await worker.email(b.message, b.env, b.ctx);
    expect(b.message.setReject).not.toHaveBeenCalled();
  });

  it("keeps the email when the API is down, and the cron delivers it later", async () => {
    mockApi(new Error("connection refused"));
    const { env, ctx, message, kv, waits } = setup();
    await worker.email(message, env, ctx);
    await Promise.all(waits);
    expect(kv.store.size).toBe(1);
    const kept = JSON.parse([...kv.store.values()][0]!);
    expect(kept.dkim).toEqual([{ domain: "linkedin.com", result: "pass" }]);

    mockApi(new Response("", { status: 530 }));
    await worker.scheduled({} as ScheduledController, env, ctx);
    expect(kv.store.size).toBe(1); // still down

    const api = mockApi(Response.json({ accepted: true }));
    await worker.scheduled({} as ScheduledController, env, ctx);
    expect(api).toHaveBeenCalledOnce();
    expect(kv.store.size).toBe(0);
  });
});
