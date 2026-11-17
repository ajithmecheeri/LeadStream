"use client";
import type { Alerts } from "@fitfirst/api";
import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorMessage, fieldErrors, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { seenAgo } from "@/lib/jobs";

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const MAX_ROLES = 5;

/** The roles (up to 5) Google Alerts are suggested for: yours, else your target roles. */
function AlertRoles({ data, busy, onSave }: { data: Alerts; busy: boolean; onSave: (roles: string[]) => Promise<boolean> }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string[]>([]);

  function start() {
    setDraft(Array.from({ length: MAX_ROLES }, (_, i) => data.roles[i] ?? ""));
    setEditing(true);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (await onSave(draft.map((r) => r.trim()).filter(Boolean))) setEditing(false);
  }

  if (!editing) {
    return (
      <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }} data-testid="alert-roles">
        <span className="subtle">Roles ({data.roles_custom ? "yours" : "from your Skill Match profiles"}):</span>
        {data.roles.length ? data.roles.map((r) => <span key={r} className="chip plain">{r}</span>) : <span className="muted">none yet</span>}
        <button type="button" className="btn btn-sm btn-ghost" onClick={start}>{data.roles.length ? "Edit roles" : "Add roles"}</button>
      </div>
    );
  }
  return (
    <form className="stack-tight" style={{ marginTop: 12 }} onSubmit={save} data-testid="alert-roles-form">
      <span className="subtle">
        Up to {MAX_ROLES} roles. Use OR (in capitals) and brackets for alternatives: each is saved in quotes, the way
        Google needs it. A role that names its city gets one alert as written; otherwise one per job location.
      </span>
      {draft.map((r, i) => (
        <input
          key={i}
          className="input"
          aria-label={`Role ${i + 1}`}
          placeholder={i === 0 ? "(Technology Director OR Engineering Director) (Bengaluru OR Bangalore)" : `Role ${i + 1} (optional)`}
          maxLength={200}
          value={r}
          onChange={(e) => setDraft((d) => d.map((x, j) => (j === i ? e.target.value : x)))}
        />
      ))}
      <div className="row">
        <button className="btn btn-sm btn-primary" disabled={busy}>Save roles</button>
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => setEditing(false)}>Cancel</button>
        {data.roles_custom ? (
          <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => void onSave([]).then((ok) => ok && setEditing(false))}>
            Use my target roles
          </button>
        ) : null}
      </div>
    </form>
  );
}

/** Find on Google → Roles (user, 2026-11-17): the roles the Google searches and the Google Alerts use, on top of
 *  the page. Up to 5 of the user's own; else the Skill Match profiles' target roles. */
export function GoogleRoles({ onSaved }: { onSaved: () => void }) {
  const [data, setData] = useState<Alerts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.alerts().then(setData).catch((e) => setError(errorMessage(e)));
  }, []);

  async function save(roles: string[]): Promise<boolean> {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      setData(await api.setAlertRoles(roles));
      setNote(roles.length ? "Roles saved. The searches and the suggested alerts below now use them." : "Back to your target roles.");
      onSaved();
      return true;
    } catch (err) {
      setError(fieldErrors(err).roles ?? errorMessage(err));
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" data-testid="google-roles">
      <div className="card-head">
        <h2>Roles to look for</h2>
        <span className="subtle">Used by the searches and the Google Alerts below</span>
      </div>
      {error ? <Notice kind="bad">{error}</Notice> : null}
      {note ? <Notice kind="good">{note}</Notice> : null}
      {data ? <AlertRoles data={data} busy={busy} onSave={save} /> : <p className="subtle">Loading…</p>}
    </section>
  );
}

/** Find on Google → Google Alerts (discovery plan decision 10): suggested alerts to create on Google, and the RSS
 * feeds the user pasted back. BrewMyJob reads the feeds three times a day; the job pages are never opened. The
 * roles are set on top of the page (GoogleRoles); `version` changes when they do. */
export function GoogleAlerts({ timeZone, version = 0 }: { timeZone: string; version?: number }) {
  const [data, setData] = useState<Alerts | null>(null);
  const [link, setLink] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.alerts());
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, version]);

  // A feed just added is read within seconds: look again shortly.
  const waiting = data?.feeds.some((f) => !f.last_read_at);
  useEffect(() => {
    if (!waiting) return;
    const t = setTimeout(() => void load(), 4000);
    return () => clearTimeout(t);
  }, [waiting, data, load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setLinkError(null);
    setNote(null);
    try {
      await api.addAlertFeed(link.trim());
      setLink("");
      setNote("Feed added. It's read now, then three times a day; its jobs appear on the Jobs page.");
      await load();
    } catch (err) {
      const fields = fieldErrors(err);
      if (fields.feed_url) setLinkError(fields.feed_url);
      else setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api.removeAlertFeed(id);
      setNote("Feed removed. Its jobs stay in your list; delete the alert on Google too.");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function copy(query: string) {
    try {
      await navigator.clipboard.writeText(query);
      setCopied(query);
    } catch {
      setCopied(null);
    }
  }

  const readTimes = data?.read_times ?? "three times a day";
  return (
    <section className="card" id="google-alerts" data-testid="google-alerts">
      <div className="card-head">
        <h2>Google Alerts</h2>
        <span className="subtle">Free · feeds read at {readTimes}</span>
      </div>
      <p className="hint">
        Google watches LinkedIn, Naukri and Foundit for new job pages that match your searches. You create each alert
        once; BrewMyJob does the rest: it reads the alert, adds the jobs and scores them. It only reads Google&apos;s
        feed, never the job sites.
      </p>
      <ol className="hint" style={{ margin: "8px 0 0 18px" }}>
        <li>Press <strong>Create alert</strong> next to a search below. Google Alerts opens with the search filled in (if it doesn&apos;t, paste it: <strong>Copy search</strong>).</li>
        <li>In <strong>Show options</strong>, set <strong>How often</strong> to <em>As-it-happens</em>, <strong>Region</strong> to <em>India</em> and <strong>Deliver to</strong> to <em>RSS feed</em>, then <strong>Create alert</strong>.</li>
        <li>On your list of alerts, copy the link of the alert&apos;s RSS icon and paste it below.</li>
      </ol>

      {error ? <Notice kind="bad">{error}</Notice> : null}
      {note ? <Notice kind="good">{note}</Notice> : null}

      {!data ? (
        <p className="subtle">Loading…</p>
      ) : (
        <>
          {data.suggestions.length ? (
            <ul className="stack-tight" style={{ marginTop: 12 }} data-testid="alert-suggestions">
              {data.suggestions.map((s) => (
                <li key={s.query} className="row" style={{ flexWrap: "wrap" }}>
                  <span>
                    <strong>{s.role}</strong> {s.place ? <span className="subtle">· {s.place}</span> : null}
                  </span>
                  <span className="spacer" />
                  {s.added ? <span className="badge badge-good">Feed added</span> : null}
                  <button type="button" className="btn btn-sm btn-ghost" onClick={() => void copy(s.query)}>
                    {copied === s.query ? "Copied" : "Copy search"}
                  </button>
                  <a className="btn btn-sm" href={s.create_url} target="_blank" rel="noopener noreferrer">Create alert ↗</a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="hint" style={{ marginTop: 12 }}>
              Add the roles you want at the top of this page (or target roles in your{" "}
              <Link href="/profile">Skill Match Profile</Link>) to get suggested alerts.
            </p>
          )}

          <form className="row" style={{ marginTop: 14, gap: 8, alignItems: "flex-start" }} onSubmit={add}>
            <div className="stack-tight" style={{ flex: 1, minWidth: 0 }}>
              <label htmlFor="alert-feed" className="sr-only">RSS feed link</label>
              <input
                id="alert-feed"
                value={link}
                onChange={(e) => setLink(e.target.value)}
                placeholder="https://www.google.com/alerts/feeds/…"
                aria-invalid={linkError ? true : undefined}
              />
              {linkError ? <span className="field-error">{linkError}</span> : null}
            </div>
            <button className="btn btn-primary" disabled={busy || link.trim().length < 10}>Add feed</button>
          </form>

          {data.feeds.length ? (
            <ul className="stack-tight" style={{ marginTop: 12 }} data-testid="alert-feeds">
              {data.feeds.map((f) => (
                <li key={f.id} className="row" data-testid="alert-feed">
                  <span style={{ minWidth: 0 }}>
                    <strong style={{ overflowWrap: "anywhere" }}>{f.query ?? "Google Alert"}</strong>
                    <br />
                    {f.last_error ? (
                      <span className="field-error">{f.last_error}</span>
                    ) : f.last_read_at ? (
                      <span className="subtle">
                        {plural(f.found, "job")} · {f.added} new for you ·{" "}
                        {f.top_matches ? <Link href="/jobs?tab=top">{plural(f.top_matches, "Top match", "Top matches")}</Link> : "0 Top matches"}
                        {f.skipped ? ` · ${plural(f.skipped, "other link")} skipped` : ""} · read {seenAgo(f.last_read_at)}
                      </span>
                    ) : (
                      <span className="subtle">Reading now…</span>
                    )}
                  </span>
                  <span className="spacer" />
                  <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => void remove(f.id)}>Remove</button>
                </li>
              ))}
            </ul>
          ) : null}
          <p className="hint" style={{ marginTop: 10 }}>
            Next read {new Date(data.next_read_at).toLocaleString("en-IN", { timeZone, hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" })}.
            Jobs from alerts are scored from their title until you paste the description on the job&apos;s page.
          </p>
        </>
      )}
    </section>
  );
}
