"use client";
import type { SentMessage, WhatsApp } from "@fitfirst/api";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { errorMessage, Field, fieldErrors, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { seenAgo } from "@/lib/jobs";

const STATUS: Record<string, { label: string; kind: "good" | "warn" | "bad" | "info" }> = {
  queued: { label: "Sending", kind: "info" },
  held: { label: "After quiet hours", kind: "info" },
  sent: { label: "Sent", kind: "good" },
  logged: { label: "Not sent (WhatsApp not set up)", kind: "warn" },
  failed: { label: "Failed", kind: "bad" },
  skipped: { label: "Not sent", kind: "warn" },
};
const KIND: Record<string, string> = { new_job: "Job alert", test: "Test", code: "Verification code" };

function MessageRow({ m, timeZone }: { m: SentMessage; timeZone: string }) {
  const s = STATUS[m.status] ?? { label: m.status, kind: "info" as const };
  const when = m.status === "held"
    ? new Date(m.send_after).toLocaleString("en-IN", { timeZone, hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" })
    : seenAgo(m.sent_at ?? m.created_at);
  return (
    <li className="row" data-testid="whatsapp-message">
      <span>
        <span className="subtle">{KIND[m.kind] ?? m.kind}: </span>
        {m.user_job_id ? <Link href={`/jobs/${m.user_job_id}`}>{m.body}</Link> : m.body}
        {m.error ? <span className="subtle"> · {m.error}</span> : null}
      </span>
      <span className="spacer" />
      <span className={`badge badge-${s.kind}`}>{s.label}</span>
      <span className="subtle num">{when}</span>
    </li>
  );
}

/** WhatsApp alerts for strong matches: add and verify a number, turn alerts on or off, send a test. */
export function WhatsAppAlerts({ timeZone }: { timeZone: string }) {
  const [wa, setWa] = useState<WhatsApp | null>(null);
  const [number, setNumber] = useState("");
  const [code, setCode] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "good" | "bad"; text: string } | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    api.whatsapp().then(setWa).catch((e) => setMsg({ kind: "bad", text: errorMessage(e) }));
  }, []);

  async function act(fn: () => Promise<WhatsApp | unknown>, done?: string) {
    setBusy(true);
    setMsg(null);
    setErrors({});
    try {
      const out = await fn();
      setWa(out && typeof out === "object" && "verified" in out ? (out as WhatsApp) : await api.whatsapp());
      if (done) setMsg({ kind: "good", text: done });
      return true;
    } catch (e) {
      setErrors(fieldErrors(e));
      setMsg({ kind: "bad", text: errorMessage(e) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function sendCode(e: FormEvent) {
    e.preventDefault();
    if (await act(() => api.setWhatsAppNumber(number), "Code sent. Check WhatsApp on that phone.")) {
      setEditing(false);
      setCode("");
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    if (await act(() => api.verifyWhatsApp(code), "Number verified. Strong matches will reach you on WhatsApp.")) setCode("");
  }

  if (!wa) return <section className="card"><div className="card-head"><h2>WhatsApp alerts</h2></div><p className="subtle">{msg?.text ?? "Loading…"}</p></section>;
  const asking = !wa.number || editing;

  return (
    <section className="card" data-testid="whatsapp">
      <div className="card-head">
        <h2>WhatsApp alerts</h2>
        <span className="subtle">
          {wa.verified ? `${wa.sent_today} of ${wa.daily_limit} today` : "A message for each new strong match"}
        </span>
      </div>
      <div className="stack-tight">
        <p className="hint" style={{ marginTop: 0 }}>
          When a new job scores at or above your search profile&apos;s strong-match threshold, BrewMyJob sends you one
          WhatsApp message with the job and a link to it. Never for a job you&apos;ve already applied to or seen
          before; held during quiet hours; at most your daily limit (below).
        </p>
        {!wa.configured ? (
          <Notice kind="warn">
            WhatsApp sending isn&apos;t set up on this server yet, so messages are written to the server log instead of
            sent. You can still add and verify your number; the code appears in the log.
          </Notice>
        ) : null}
        {msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null}

        {asking ? (
          <form className="row" onSubmit={sendCode} style={{ alignItems: "flex-end" }}>
            <Field label="WhatsApp number" htmlFor="wa-number" error={errors.number} hint="With the country code, e.g. +91 98765 43210">
              <input id="wa-number" className="input num" inputMode="tel" autoComplete="tel" value={number} onChange={(e) => setNumber(e.target.value)} />
            </Field>
            <button className="btn btn-primary" disabled={busy || number.replace(/\D/g, "").length < 10}>Send code</button>
            {editing ? <button type="button" className="btn btn-ghost" onClick={() => setEditing(false)}>Cancel</button> : null}
          </form>
        ) : (
          <div className="row">
            <span>
              <strong className="num">{wa.number}</strong>{" "}
              <span className={`badge badge-${wa.verified ? "good" : "warn"}`}>{wa.verified ? "Verified" : "Not verified"}</span>
            </span>
            <span className="spacer" />
            <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => { setNumber(""); setEditing(true); }}>Change</button>
            <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => act(() => api.removeWhatsApp(), "Number removed.")}>Remove</button>
          </div>
        )}

        {wa.number && !wa.verified && !wa.code_sent && !editing ? (
          <div className="row">
            <span className="subtle">Verify this number to start alerts: BrewMyJob sends it a 6-digit code on WhatsApp.</span>
            <span className="spacer" />
            <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => act(() => api.sendWhatsAppCode(), "Code sent. Check WhatsApp on that phone.")}>Send code</button>
          </div>
        ) : null}

        {wa.number && !wa.verified && wa.code_sent && !editing ? (
          <form className="row" onSubmit={verify} style={{ alignItems: "flex-end" }}>
            <Field label="Code from WhatsApp" htmlFor="wa-code" error={errors.code} hint="6 digits; it works for 10 minutes.">
              <input id="wa-code" className="input num" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
            </Field>
            <button className="btn btn-primary" disabled={busy || code.length !== 6}>Verify</button>
            <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => act(() => api.sendWhatsAppCode(), "New code sent.")}>Send a new code</button>
          </form>
        ) : null}

        {wa.verified ? (
          <div className="row">
            <label className="check">
              <input type="checkbox" checked={wa.jobs} disabled={busy} onChange={(e) => { const on = e.target.checked; void act(() => api.setWhatsAppJobs(on)); }} />
              <span>Send strong matches on WhatsApp</span>
            </label>
            <span className="spacer" />
            <button className="btn btn-sm" disabled={busy} onClick={() => act(() => api.testWhatsApp(), "Test sent: your best open match.")}>Send a test</button>
          </div>
        ) : null}

        {wa.recent.length ? (
          <details>
            <summary className="subtle">Recent messages ({wa.recent.length})</summary>
            <ul className="stack-tight" style={{ marginTop: 8 }}>
              {wa.recent.map((m) => <MessageRow key={m.id} m={m} timeZone={timeZone} />)}
            </ul>
          </details>
        ) : null}
      </div>
    </section>
  );
}
