"use client";
import type { InboxMessage, Mail } from "@fitfirst/api";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import { errorMessage, Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { MESSAGE_STATUS, parserLabel, toBase64 } from "@/lib/jobs";

export default function InboxPage() {
  const [messages, setMessages] = useState<InboxMessage[] | null>(null);
  const [mail, setMail] = useState<Mail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [m, msgs] = await Promise.all([api.mail(), api.inbox({ limit: 100 })]);
      setMail(m);
      setMessages(msgs);
      return msgs;
    } catch (e) {
      setError(errorMessage(e));
      return null;
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // While an email is still being read, check again every two seconds (the worker takes a moment).
  const reading = messages?.some((m) => m.status === "accepted") ?? false;
  useEffect(() => {
    if (!reading) return;
    const t = setInterval(() => void load(), 2000);
    return () => clearInterval(t);
  }, [reading, load]);

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!files.length) return;
    setUploading(true);
    setError(null);
    setNote(null);
    const problems: string[] = [];
    let sent = 0;
    for (const f of files) {
      try {
        await api.uploadEmail(toBase64(new Uint8Array(await f.arrayBuffer())));
        sent++;
      } catch (err) {
        problems.push(`${f.name}: ${errorMessage(err)}`);
      }
    }
    setUploading(false);
    if (sent) setNote(`${sent} email${sent > 1 ? "s" : ""} delivered. Jobs appear on the Jobs page once read.`);
    if (problems.length) setError(problems.join("\n"));
    await load();
  }

  if (!messages || !mail) return error ? <Notice kind="bad">{error}</Notice> : <div className="loading">Loading…</div>;

  return (
    <>
      <PageHeader
        title="Inbox"
        sub="Alert emails that reached your BrewMyJob address, and what was found in each."
        actions={
          <>
            {mail.upload_enabled ? (
              <>
                <input ref={fileRef} type="file" accept=".eml,message/rfc822" multiple hidden onChange={upload} data-testid="eml-input" />
                <button className="btn btn-sm" disabled={uploading} onClick={() => fileRef.current?.click()}
                  title="Local development only: deliver a saved alert email as if it had been forwarded">
                  {uploading ? "Uploading…" : "Upload .eml"}
                </button>
              </>
            ) : null}
            <Link className="btn btn-sm" href="/settings/mail">Mail setup</Link>
          </>
        }
      />
      {note ? <div style={{ marginBottom: 12 }}><Notice kind="good">{note}</Notice></div> : null}
      {error ? <div style={{ marginBottom: 12, whiteSpace: "pre-line" }}><Notice kind="bad">{error}</Notice></div> : null}
      {messages.length === 0 ? (
        <section className="card empty">
          <h2>Nothing received yet</h2>
          <p className="muted">
            Forward LinkedIn and Naukri job-alert emails to <code className="num">{mail.address}</code>.{" "}
            <Link href="/settings/mail">How to set up forwarding</Link>.
            {mail.upload_enabled ? " Or upload a saved alert (.eml) with the button above." : ""}
          </p>
        </section>
      ) : (
        <section className="card flush">
          <table className="table">
            <thead>
              <tr><th>Received</th><th>Email</th><th>What it was</th><th className="right">Jobs</th><th>Status</th></tr>
            </thead>
            <tbody>
              {messages.map((m) => {
                const st = MESSAGE_STATUS[m.status] ?? { label: m.status, kind: "info" as const };
                return (
                  <tr key={m.id} data-testid="inbox-row">
                    <td className="num nowrap">{new Date(m.received_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</td>
                    <td>
                      <div className="clip">{m.subject ?? "(no subject)"}</div>
                      <div className="subtle">{m.sender}{m.channel === "paste" ? " · uploaded" : ""}</div>
                    </td>
                    <td>
                      {m.status === "accepted" ? "…" : parserLabel(m.parser)}
                      {m.alert_name ? <div className="subtle">“{m.alert_name}”</div> : null}
                    </td>
                    <td className="right num">{m.cards_found ?? "–"}</td>
                    <td>
                      <span className={`badge badge-${st.kind}`}>{st.label}</span>
                      {m.error ? <div className="subtle" title={m.error}>{m.error.slice(0, 80)}</div> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
