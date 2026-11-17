"use client";
import type { AppliedCompany, ConnectionList, Daily, InviteNote, NetworkSummary, OutreachDetail, OutreachList, OutreachStage, Suggestion, WarmPath } from "@fitfirst/api";
import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorMessage, Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { toBase64 } from "@/lib/jobs";
import { KIND_LABEL, personLine, progress, STAGE_LABEL, STAGES } from "@/lib/networking";

type Tab = "today" | "warm" | "outreach" | "connections";
const TABS: { value: Tab; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "warm", label: "Warm paths" },
  { value: "outreach", label: "Outreach" },
  { value: "connections", label: "Connections" },
];

function CopyNote({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button type="button" className="btn btn-sm" onClick={async () => {
      await navigator.clipboard.writeText(text).catch(() => undefined);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }}>
      {copied ? "Copied" : "Copy note"}
    </button>
  );
}

/** One suggestion: who, why, the note, and the buttons. Sending happens on LinkedIn, by the user. */
function SuggestionCard({ s, onChange }: { s: Suggestion; onChange: (s: Suggestion) => void }) {
  const [found, setFound] = useState<{ name: string; profile_url: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function mark(action: "sent" | "skipped", e?: FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const person = found && (found.name.trim() || found.profile_url.trim())
        ? { name: found.name.trim() || null, profile_url: found.profile_url.trim() || null, title: s.role }
        : null;
      onChange(await api.markSuggestion(s.id, { action, person }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const open = s.status === "open";
  return (
    <li className={`card suggestion ${open ? "" : "done"}`} data-testid="suggestion">
      <div className="row">
        <span className={`badge ${s.kind === "followup" ? "badge-warn" : s.kind === "warm" ? "badge-good" : "badge-info"}`}>{KIND_LABEL[s.kind]}</span>
        <strong>{s.kind === "target" ? `${s.role} at ${s.company}` : s.name}</strong>
        {s.kind !== "target" && personLine(s) ? <span className="subtle">{personLine(s)}</span> : null}
        <span className="spacer" />
        {!open ? <span className="badge">{s.status === "done" ? "Sent" : "Skipped"}</span> : null}
      </div>
      <div className="muted">{s.why}</div>
      {s.user_job_id && s.job_title ? (
        <div className="subtle">For <Link href={`/jobs/${s.user_job_id}`}>{s.job_title}</Link>{s.job_score !== null ? ` · ${s.job_score}% match` : ""}</div>
      ) : null}
      {open ? (
        <>
          <div className="note" data-testid="note">{s.note}</div>
          <div className="row">
            {s.profile_url ? <a className="btn btn-sm" href={s.profile_url} target="_blank" rel="noopener noreferrer">Open profile on LinkedIn ↗</a> : null}
            {s.search_url ? <a className="btn btn-sm" href={s.search_url} target="_blank" rel="noopener noreferrer">Search on LinkedIn ↗</a> : null}
            <CopyNote text={s.note} />
            <span className="spacer" />
            {s.kind === "target" && !found ? (
              <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => setFound({ name: "", profile_url: "" })}>I sent it</button>
            ) : s.kind !== "target" ? (
              <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => mark("sent")}>I sent it</button>
            ) : null}
            <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => mark("skipped")}>Skip</button>
          </div>
          {found ? (
            <form className="row" onSubmit={(e) => mark("sent", e)}>
              <input className="input grow" style={{ flex: 1, minWidth: 160, width: "auto" }} aria-label="Who you wrote to" placeholder="Who you wrote to (optional)"
                value={found.name} onChange={(e) => { const v = e.target.value; setFound((f) => (f ? { ...f, name: v } : f)); }} />
              <input className="input grow" style={{ flex: 1, minWidth: 200, width: "auto" }} aria-label="Their LinkedIn profile" placeholder="Their LinkedIn profile (optional)"
                value={found.profile_url} onChange={(e) => { const v = e.target.value; setFound((f) => (f ? { ...f, profile_url: v } : f)); }} />
              <button className="btn btn-sm btn-primary" disabled={busy}>Save as sent</button>
            </form>
          ) : null}
        </>
      ) : null}
      {error ? <Notice kind="bad">{error}</Notice> : null}
    </li>
  );
}

const INVITE_LIMIT = 300; // LinkedIn's limit for a note on an invitation

/** The user's own note for invitations to people they don't know yet (user feedback 2026-11-11). */
function InviteNoteEditor({ onSaved }: { onSaved: () => void }) {
  const [saved, setSaved] = useState<InviteNote | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    api.inviteNote().then((n) => { setSaved(n); setText(n.note ?? ""); }).catch((e) => setError(errorMessage(e)));
  }, []);

  async function save(note: string | null, e?: FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const n = await api.setInviteNote(note);
      setSaved(n);
      setText(n.note ?? "");
      setDone(true);
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!saved) return error ? <Notice kind="bad">{error}</Notice> : null;
  return (
    <details className="card" data-testid="invite-note">
      <summary><strong>Your invitation note</strong> <span className="subtle">· for people you don&apos;t know yet{saved.note ? " · your own" : " · ours"}</span></summary>
      <form className="stack" onSubmit={(e) => save(text, e)} style={{ marginTop: 12 }}>
        <p className="subtle">
          Used on &ldquo;find someone&rdquo; suggestions. Your first name is added at the end when it fits; LinkedIn allows {INVITE_LIMIT} characters.
          Notes to people you already know stay about the job. Leave it empty to use ours.
        </p>
        <textarea
          className="textarea" rows={4} maxLength={INVITE_LIMIT} value={text} data-testid="invite-note-text"
          placeholder={saved.example} onChange={(e) => { const v = e.target.value; setText(() => v); setDone(false); }}
        />
        <div className="row">
          <span className="subtle">{text.length} / {INVITE_LIMIT}</span>
          <span className="spacer" />
          {saved.note ? <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => save(null)}>Use ours</button> : null}
          <button className="btn btn-sm btn-primary" disabled={busy || text.trim() === (saved.note ?? "")}>Save note</button>
        </div>
        {done ? <Notice kind="good">Saved. Today&apos;s suggestions use it now.</Notice> : null}
        {error ? <Notice kind="bad">{error}</Notice> : null}
      </form>
    </details>
  );
}

const appliedDay = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

/** One company the user applied to: LinkedIn searches for its HR and leaders (opened by the user, in their own
 * browser), a note to copy, people they already know there, and a way to record who they wrote to. */
function AppliedCard({ a, onSaved }: { a: AppliedCompany; onSaved: () => void }) {
  const [form, setForm] = useState<{ name: string; title: string; profile_url: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      await api.addOutreach({
        person_name: form.name.trim(),
        title: form.title.trim() || null,
        profile_url: form.profile_url.trim() || null,
        company: a.company,
        user_job_id: a.user_job_id,
        note: a.note,
      });
      setForm(null);
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="card suggestion" data-testid="applied-company">
      <div className="row">
        <span className="badge badge-info">Applied {appliedDay(a.applied_on)}</span>
        <strong>{a.company}</strong>
        <span className="subtle">· <Link href={`/jobs/${a.user_job_id}`}>{a.job_title}</Link></span>
        <span className="spacer" />
        {a.contacted ? <span className="badge badge-good">{a.contacted} contacted</span> : null}
      </div>
      <div className="muted">Find someone in HR or the team&apos;s leadership and ask about your application.</div>
      <div className="row" style={{ flexWrap: "wrap" }}>
        {a.searches.map((s) => (
          <a key={s.kind} className="btn btn-sm" href={s.url} target="_blank" rel="noopener noreferrer" data-testid={`search-${s.kind}`}>
            {s.label} on LinkedIn ↗
          </a>
        ))}
        <CopyNote text={a.note} />
        <span className="spacer" />
        {!form ? <button type="button" className="btn btn-sm btn-primary" onClick={() => setForm({ name: "", title: "", profile_url: "" })}>I wrote to someone</button> : null}
      </div>
      {a.people.length ? (
        <div className="subtle">
          You know {a.total_people === 1 ? "someone" : `${a.total_people} people`} here:{" "}
          {a.people.map((p, i) => (
            <span key={p.id}>
              {i ? ", " : ""}
              {p.profile_url ? <a href={p.profile_url} target="_blank" rel="noopener noreferrer">{p.name}</a> : p.name}
              {p.position ? ` (${p.position})` : ""}
            </span>
          ))}
        </div>
      ) : null}
      {form ? (
        <form className="row" style={{ flexWrap: "wrap" }} onSubmit={save}>
          <input className="input" style={{ flex: 1, minWidth: 140, width: "auto" }} aria-label="Their name" placeholder="Their name" required
            value={form.name} onChange={(e) => { const v = e.target.value; setForm((f) => (f ? { ...f, name: v } : f)); }} />
          <input className="input" style={{ flex: 1, minWidth: 140, width: "auto" }} aria-label="Their role" placeholder="Their role (HR, Director…)"
            value={form.title} onChange={(e) => { const v = e.target.value; setForm((f) => (f ? { ...f, title: v } : f)); }} />
          <input className="input" style={{ flex: 2, minWidth: 180, width: "auto" }} aria-label="Their LinkedIn profile" placeholder="Their LinkedIn profile (optional)"
            value={form.profile_url} onChange={(e) => { const v = e.target.value; setForm((f) => (f ? { ...f, profile_url: v } : f)); }} />
          <button className="btn btn-sm btn-primary" disabled={busy || !form.name.trim()}>Save as sent</button>
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => setForm(null)}>Cancel</button>
        </form>
      ) : null}
      {error ? <Notice kind="bad">{error}</Notice> : null}
    </li>
  );
}

/** Companies applied to in the last 60 days (user feedback 2026-11-15). */
function AppliedCompanies() {
  const [items, setItems] = useState<AppliedCompany[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api.appliedCompanies().then((r) => setItems(r.items)).catch((e) => setError(errorMessage(e)));
  }, []);
  useEffect(() => { load(); }, [load]);
  if (error) return <Notice kind="bad">{error}</Notice>;
  if (!items) return null;
  return (
    <section className="stack" data-testid="applied-companies">
      <h2 style={{ margin: "8px 0 0" }}>Companies you applied to</h2>
      {items.length ? (
        <ul className="job-list">
          {items.map((a) => <AppliedCard key={a.user_job_id} a={a} onSaved={load} />)}
        </ul>
      ) : (
        <section className="card empty">
          <p className="muted">When you mark a job Applied, its company appears here with LinkedIn searches for its HR and leaders.</p>
        </section>
      )}
    </section>
  );
}

function Today({ summary }: { summary: NetworkSummary }) {
  const [day, setDay] = useState<Daily | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (regenerate = false) => {
    setBusy(true);
    setError(null);
    try {
      setDay(await api.daily(regenerate ? { regenerate: true } : undefined));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  if (error) return <Notice kind="bad">{error}</Notice>;
  if (!day) return <div className="loading">Loading…</div>;
  return (
    <div className="stack">
      <div className="row">
        <span className="muted" data-testid="today-progress">{day.items.length ? progress(day.items) : "Nothing to suggest today"}</span>
        <span className="subtle">· {day.weekly_sent} of {day.weekly_limit} this week</span>
        <span className="spacer" />
        <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => load(true)}>Suggest others</button>
      </div>
      {day.weekly_sent >= day.weekly_limit ? (
        <Notice kind="warn">You&apos;ve reached your weekly limit, so only follow-ups are suggested. LinkedIn also limits invitations per week.</Notice>
      ) : null}
      {!day.items.length ? (
        <section className="card empty">
          {summary.connections === 0 ? (
            <p className="muted">Import your LinkedIn connections to see who you know at the companies hiring for your Top matches.</p>
          ) : (
            <p className="muted">No one to suggest today. Suggestions come from your Top matches: as more alerts arrive, more appear.</p>
          )}
        </section>
      ) : (
        <ul className="job-list">
          {day.items.map((s) => (
            <SuggestionCard key={s.id} s={s} onChange={(n) => setDay((d) => (d ? { ...d, items: d.items.map((x) => (x.id === n.id ? n : x)) } : d))} />
          ))}
        </ul>
      )}
      <AppliedCompanies />
      <InviteNoteEditor onSaved={() => void load()} />
      <p className="subtle">
        BrewMyJob never sends anything on LinkedIn. Open the profile, paste the note, send it yourself, then press &ldquo;I sent it&rdquo; so it&apos;s tracked under Outreach.
      </p>
    </div>
  );
}

function WarmPaths() {
  const [items, setItems] = useState<WarmPath[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.warmPaths().then((w) => setItems(w.items)).catch((e) => setError(errorMessage(e))); }, []);
  if (error) return <Notice kind="bad">{error}</Notice>;
  if (!items) return <div className="loading">Loading…</div>;
  if (!items.length) return <section className="card empty"><p className="muted">No one you know works at the companies of your Top matches yet.</p></section>;
  return (
    <ul className="job-list">
      {items.map((w) => (
        <li key={w.user_job_id} className="card" data-testid="warm-path">
          <div className="row">
            <Link className="job-title" href={`/jobs/${w.user_job_id}`}>{w.title}</Link>
            <span className="muted">{w.company}</span>
            {w.score !== null ? <span className="badge">{w.score}%</span> : null}
            {w.status === "applied" ? <span className="badge badge-info">Applied</span> : null}
          </div>
          <ul className="doc-list" style={{ marginTop: 6 }}>
            {w.people.map((p) => (
              <li key={p.id}>
                <div className="grow stack-tight"><strong>{p.name}</strong><span className="subtle">{personLine({ title: p.position, company: p.company })}</span></div>
                {p.profile_url ? <a className="btn btn-sm" href={p.profile_url} target="_blank" rel="noopener noreferrer">Profile ↗</a> : null}
              </li>
            ))}
          </ul>
          {w.total_people > w.people.length ? <p className="subtle">and {w.total_people - w.people.length} more</p> : null}
        </li>
      ))}
    </ul>
  );
}

function OutreachTab() {
  const [list, setList] = useState<OutreachList | null>(null);
  const [stage, setStage] = useState<OutreachStage | "">("");
  const [open, setOpen] = useState<OutreachDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setList(await api.outreachList(stage || undefined));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [stage]);
  useEffect(() => { void load(); }, [load]);

  async function move(id: string, version: number, next: OutreachStage) {
    setError(null);
    try {
      const d = await api.updateOutreach(id, { stage: next, version });
      if (open?.id === id) setOpen(d);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  if (!list) return error ? <Notice kind="bad">{error}</Notice> : <div className="loading">Loading…</div>;
  const all = Object.values(list.counts).reduce((a, b) => a + b, 0);
  return (
    <div className="stack">
      <div className="toggle-group" role="group" aria-label="Stage">
        <button type="button" aria-pressed={stage === ""} onClick={() => setStage("")}>All ({all})</button>
        {STAGES.map((s) => (
          <button key={s.value} type="button" aria-pressed={stage === s.value} onClick={() => setStage(s.value)}>
            {s.label} ({list.counts[s.value] ?? 0})
          </button>
        ))}
      </div>
      {error ? <Notice kind="bad">{error}</Notice> : null}
      {!list.items.length ? (
        <section className="card empty"><p className="muted">Nothing here yet. People you mark as sent from Today appear here.</p></section>
      ) : (
        <ul className="job-list">
          {list.items.map((o) => (
            <li key={o.id} className="card" data-testid="outreach">
              <div className="row">
                <strong>{o.person_name ?? "Someone"}</strong>
                <span className="subtle">{personLine(o)}</span>
                <span className="spacer" />
                <select className="select narrow" style={{ width: "auto" }} aria-label={`Stage for ${o.person_name ?? "outreach"}`} value={o.stage}
                  onChange={(e) => move(o.id, o.version, e.target.value as OutreachStage)}>
                  {STAGES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </div>
              <div className="row subtle">
                <span>{STAGE_LABEL[o.stage]} {new Date(o.stage_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</span>
                {o.followed_up_at ? <span>· followed up {new Date(o.followed_up_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</span> : null}
                {o.user_job_id && o.job_title ? <span>· for <Link href={`/jobs/${o.user_job_id}`}>{o.job_title}</Link></span> : null}
                {o.profile_url ? <a href={o.profile_url} target="_blank" rel="noopener noreferrer">Profile ↗</a> : null}
                <button type="button" className="btn btn-sm btn-ghost" onClick={async () => setOpen(open?.id === o.id ? null : await api.outreach(o.id))}>
                  {open?.id === o.id ? "Hide history" : "History"}
                </button>
              </div>
              {open?.id === o.id ? (
                <ul className="timeline" style={{ marginTop: 8 }}>
                  {open.events.map((e) => (
                    <li key={e.id}>
                      <span className="subtle">{new Date(e.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</span>
                      <span>{e.kind === "sent" ? "Sent" : e.kind === "followed_up" ? "Followed up" : e.kind === "stage" ? `Moved to ${STAGE_LABEL[e.stage as OutreachStage] ?? e.stage}` : e.note}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Connections({ summary, onImported }: { summary: NetworkSummary; onImported: () => void }) {
  const [q, setQ] = useState("");
  const [list, setList] = useState<ConnectionList | null>(null);
  const [keepEmail, setKeepEmail] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "good" | "bad"; text: string } | null>(null);

  const load = useCallback(async (query: string) => {
    try {
      setList(await api.connections({ q: query || undefined, limit: 50 }));
    } catch (e) {
      setMessage({ kind: "bad", text: errorMessage(e) });
    }
  }, []);
  useEffect(() => {
    const t = setTimeout(() => void load(q), 250);
    return () => clearTimeout(t);
  }, [q, load, summary.connections]);

  async function upload(file: File) {
    setBusy(true);
    setMessage(null);
    try {
      const r = await api.importConnections({ file_name: file.name, content_base64: toBase64(new Uint8Array(await file.arrayBuffer())), keep_email: keepEmail });
      setMessage({ kind: "good", text: `${r.total} connections read: ${r.added} new, ${r.updated} updated.` });
      onImported();
    } catch (e) {
      setMessage({ kind: "bad", text: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  }

  async function removeAll() {
    if (!window.confirm("Remove all your imported connections? Your outreach records stay.")) return;
    try {
      await api.deleteConnections();
      setMessage({ kind: "good", text: "All connections removed." });
      onImported();
    } catch (e) {
      setMessage({ kind: "bad", text: errorMessage(e) });
    }
  }

  return (
    <div className="stack">
      <section className="card stack">
        <div className="card-head"><h2>Import from LinkedIn</h2>{summary.last_import ? <span className="subtle">Last import {new Date(summary.last_import.created_at).toLocaleDateString("en-IN")}</span> : null}</div>
        <ol className="howto">
          <li>On LinkedIn, open <strong>Settings → Data privacy → Get a copy of your data</strong>.</li>
          <li>Choose <strong>Connections</strong> and request the archive. LinkedIn emails you a link, usually within minutes.</li>
          <li>Upload the ZIP (or the <code>Connections.csv</code> inside it) here. Importing again later updates the list.</li>
        </ol>
        <label className="check"><input type="checkbox" checked={keepEmail} onChange={(e) => setKeepEmail(e.target.checked)} /> Keep email addresses (most are blank; not needed for warm paths)</label>
        <div className="row">
          <label className="btn btn-primary btn-sm">
            {busy ? "Importing…" : "Upload connections"}
            <input type="file" accept=".csv,.zip" hidden data-testid="connections-input" disabled={busy}
              onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void upload(f); }} />
          </label>
          {summary.connections ? <button className="btn btn-sm btn-ghost danger" onClick={removeAll}>Remove all</button> : null}
        </div>
        {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
        <p className="subtle">The file itself isn&apos;t kept, only the names, companies, positions and profile links. BrewMyJob never logs in to LinkedIn.</p>
      </section>
      {summary.connections ? (
        <section className="card stack">
          <input className="input" type="search" aria-label="Search connections" placeholder="Search name, company or position" value={q} onChange={(e) => setQ(e.target.value)} />
          {list ? (
            <>
              <p className="subtle" data-testid="connections-total">{list.total} connection{list.total === 1 ? "" : "s"}</p>
              <ul className="doc-list">
                {list.items.map((c) => (
                  <li key={c.id}>
                    <div className="grow stack-tight"><strong>{c.name}</strong><span className="subtle">{personLine({ title: c.position, company: c.company })}</span></div>
                    {c.profile_url ? <a className="btn btn-sm btn-ghost" href={c.profile_url} target="_blank" rel="noopener noreferrer">Profile ↗</a> : null}
                  </li>
                ))}
              </ul>
              {list.total > list.items.length ? <p className="subtle">Showing the first {list.items.length}. Search to narrow it down.</p> : null}
            </>
          ) : <div className="loading">Loading…</div>}
        </section>
      ) : null}
    </div>
  );
}

export default function NetworkingPage() {
  const [tab, setTab] = useState<Tab>("today");
  const [summary, setSummary] = useState<NetworkSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadSummary = useCallback(async () => {
    try {
      const s = await api.networkSummary();
      setSummary(s);
      return s;
    } catch (e) {
      setError(errorMessage(e));
      return null;
    }
  }, []);
  useEffect(() => {
    void loadSummary().then((s) => { if (s && s.connections === 0) setTab("connections"); });
  }, [loadSummary]);

  if (error) return <Notice kind="bad">{error}</Notice>;
  if (!summary) return <div className="loading">Loading…</div>;
  return (
    <>
      <PageHeader title="Networking" sub="Who you know at the companies hiring for your Top matches, a few people to contact each day, and the notes to send. You send everything yourself." />
      <div className="stat-row" style={{ marginBottom: 14 }}>
        <div className="stat"><b data-testid="connections-count">{summary.connections}</b><span className="subtle">connections</span></div>
        <div className="stat"><b>{summary.companies}</b><span className="subtle">companies</span></div>
        <div className="stat"><b data-testid="warm-jobs">{summary.warm_jobs}</b><span className="subtle">matching jobs where you know someone</span></div>
      </div>
      <div className="tabs" role="group" aria-label="Networking">
        {TABS.map((t) => (
          <button key={t.value} type="button" aria-pressed={tab === t.value} onClick={() => setTab(t.value)}>{t.label}</button>
        ))}
      </div>
      <div>
        {tab === "today" ? <Today summary={summary} /> : null}
        {tab === "warm" ? <WarmPaths /> : null}
        {tab === "outreach" ? <OutreachTab /> : null}
        {tab === "connections" ? <Connections summary={summary} onImported={() => void loadSummary()} /> : null}
      </div>
    </>
  );
}
