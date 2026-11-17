"use client";
import type { Application, ApplicationDetail, ApplicationList, ApplicationQuery, ApplicationStatus } from "@fitfirst/api";
import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorMessage, Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { APPLICATION_STATUS, isoDay, periodRange } from "@/lib/jobs";

const STATUSES = Object.keys(APPLICATION_STATUS) as ApplicationStatus[];
type Period = "any" | "day" | "month" | "year";

const fmt = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

/** The history of one application, and a note box. */
function Timeline({ app, onChange }: { app: ApplicationDetail; onChange: (a: ApplicationDetail) => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onChange(await api.addApplicationNote(app.id, note));
      setNote("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ marginTop: 12, gap: 10 }} data-testid="timeline">
      <ul className="timeline">
        {app.events.map((e) => (
          <li key={e.id}>
            <span className="subtle">{new Date(e.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</span>
            <span>
              {e.kind === "applied"
                ? "Marked as applied"
                : e.kind === "status"
                  ? `${APPLICATION_STATUS[e.from_status ?? ""]?.label ?? e.from_status} → ${APPLICATION_STATUS[e.to_status ?? ""]?.label ?? e.to_status}`
                  : e.kind === "follow_up"
                    ? e.note ? `Follow-up set for ${fmt(e.note)}` : "Follow-up date removed"
                    : e.note}
            </span>
          </li>
        ))}
      </ul>
      <form className="row" onSubmit={add}>
        <input className="input grow" aria-label="Add a note" placeholder="Add a note: who you spoke to, what's next" value={note}
          onChange={(e) => setNote(e.target.value)} style={{ flex: 1, minWidth: 220, width: "auto" }} />
        <button className="btn btn-sm" disabled={busy || !note.trim()}>Add note</button>
      </form>
      {error ? <Notice kind="bad">{error}</Notice> : null}
    </div>
  );
}

function AppCard(props: { app: Application; open: boolean; onToggle: () => void; onSaved: (a: ApplicationDetail) => void }) {
  const { app } = props;
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (props.open && !detail) api.application(app.id).then(setDetail).catch((e) => setError(errorMessage(e)));
  }, [props.open, detail, app.id]);

  async function save(body: Omit<Parameters<typeof api.updateApplication>[1], "version">) {
    setBusy(true);
    setError(null);
    try {
      const d = await api.updateApplication(app.id, { ...body, version: detail?.version ?? app.version });
      setDetail(d);
      props.onSaved(d);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const status = APPLICATION_STATUS[app.status];
  return (
    <li className={`card app-card ${app.follow_up_due ? "due" : ""}`} data-testid="application">
      <div className="job-main">
        <div className="row">
          <Link className="job-title" href={`/jobs/${app.job.user_job_id}`}>{app.job.title}</Link>
          <span className={`badge badge-${status?.kind || "plain"}`}>{status?.label ?? app.status}</span>
          {app.follow_up_due ? <span className="badge badge-warn" data-testid="follow-up-due">Follow up</span> : null}
        </div>
        <div className="muted">{app.job.company ?? "Company not named"}{app.job.location ? ` · ${app.job.location}` : ""}</div>
        <div className="row subtle">
          <span>Applied {fmt(app.applied_on)}</span>
          {app.resume_label ? <><span>·</span><span>Resume: {app.resume_label}</span></> : null}
          {app.cover_letter_label ? <><span>·</span><span>Cover letter: {app.cover_letter_label}</span></> : null}
          {app.job.score !== null ? <><span>·</span><span>Match {app.job.score}%</span></> : null}
        </div>
        <div className="row" style={{ marginTop: 6 }}>
          <label className="row subtle" style={{ gap: 6 }}>
            Status
            <select className="select narrow" style={{ width: "auto" }} aria-label={`Status of ${app.job.title}`} value={app.status} disabled={busy}
              onChange={(e) => save({ status: e.target.value as ApplicationStatus })}>
              {STATUSES.map((s) => <option key={s} value={s}>{APPLICATION_STATUS[s]!.label}</option>)}
            </select>
          </label>
          <label className="row subtle" style={{ gap: 6 }}>
            Follow up on
            <input className="input narrow" style={{ width: "auto" }} type="date" aria-label={`Follow-up date for ${app.job.title}`}
              value={app.follow_up_on ?? ""} disabled={busy} onChange={(e) => save({ follow_up_on: e.target.value || null })} />
          </label>
          <span className="spacer" />
          <button type="button" className="btn btn-sm btn-ghost" onClick={props.onToggle} aria-expanded={props.open}>
            {props.open ? "Hide history" : "History and notes"}
          </button>
        </div>
        {error ? <Notice kind="bad">{error}</Notice> : null}
        {props.open && detail ? <Timeline app={detail} onChange={(d) => { setDetail(d); props.onSaved(d); }} /> : null}
      </div>
    </li>
  );
}

export default function ApplicationsPage() {
  const [status, setStatus] = useState<ApplicationStatus | "">("");
  const [due, setDue] = useState(false);
  const [period, setPeriod] = useState<Period>("any");
  const [day, setDay] = useState(isoDay(new Date()));
  const [month, setMonth] = useState(isoDay(new Date()).slice(0, 7));
  const [year, setYear] = useState(new Date().getFullYear());
  const [list, setList] = useState<ApplicationList | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // ?open=<id> (from a job's "Track application") opens that application's history.
  useEffect(() => {
    setOpen(new URLSearchParams(window.location.search).get("open") || null);
  }, []);

  const query = useCallback((): ApplicationQuery => {
    const range =
      period === "day" ? { from: day, to: day }
        : period === "month" ? periodRange(Number(month.slice(0, 4)), Number(month.slice(5, 7)))
          : period === "year" ? periodRange(year)
            : {};
    return { ...(status ? { status } : {}), ...(due ? { due: true } : {}), ...range, limit: 100 };
  }, [status, due, period, day, month, year]);

  const load = useCallback(async () => {
    setError(null);
    try {
      setList(await api.applications(query()));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [query]);

  useEffect(() => {
    void load();
  }, [load]);

  const years = Array.from({ length: 4 }, (_, i) => new Date().getFullYear() - i);
  const all = list ? Object.values(list.counts).reduce((a, b) => a + b, 0) : 0;

  return (
    <>
      <PageHeader title="Applications" sub="Every job you marked Applied, with where it stands. You apply on the portal; BrewMyJob keeps track." />
      <div className="tabs" role="group" aria-label="Application status">
        <button type="button" aria-pressed={status === ""} onClick={() => setStatus("")}>All<span className="count">{all}</span></button>
        {STATUSES.filter((s) => (list?.counts[s] ?? 0) > 0 || status === s).map((s) => (
          <button key={s} type="button" aria-pressed={status === s} onClick={() => setStatus(s)}>
            {APPLICATION_STATUS[s]!.label}<span className="count">{list?.counts[s] ?? 0}</span>
          </button>
        ))}
      </div>
      <section className="card filters" aria-label="Filters">
        <label className="check">
          <input type="checkbox" checked={due} onChange={(e) => setDue(e.target.checked)} />
          Follow-ups due{list?.follow_ups_due ? ` (${list.follow_ups_due})` : ""}
        </label>
        <select className="select narrow" aria-label="Applied" value={period} onChange={(e) => setPeriod(e.target.value as Period)}>
          <option value="any">Applied any time</option>
          <option value="day">On a day…</option>
          <option value="month">In a month…</option>
          <option value="year">In a year…</option>
        </select>
        {period === "day" ? <input className="input narrow" type="date" aria-label="Day" value={day} onChange={(e) => setDay(e.target.value)} /> : null}
        {period === "month" ? <input className="input narrow" type="month" aria-label="Month" value={month} onChange={(e) => setMonth(e.target.value)} /> : null}
        {period === "year" ? (
          <select className="select narrow" aria-label="Year" value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        ) : null}
      </section>

      {error ? <div style={{ margin: "16px 0" }}><Notice kind="bad">{error}</Notice></div> : null}
      {!list ? (
        <div className="loading">Loading…</div>
      ) : list.items.length === 0 ? (
        <section className="card empty">
          {all === 0 ? (
            <>
              <h2>No applications yet</h2>
              <p className="muted">After you apply for a job on LinkedIn or Naukri, open it in <Link href="/jobs">Jobs</Link> and press Applied.</p>
            </>
          ) : (
            <p className="muted">No applications match these filters.</p>
          )}
        </section>
      ) : (
        <>
          <p className="subtle" style={{ margin: "14px 2px 8px" }} data-testid="applications-total">
            {list.total} application{list.total === 1 ? "" : "s"}
          </p>
          <ul className="app-list">
            {list.items.map((a) => (
              <AppCard key={a.id} app={a} open={open === a.id} onToggle={() => setOpen((o) => (o === a.id ? null : a.id))}
                onSaved={(d) => {
                  setList((l) => (l ? { ...l, items: l.items.map((x) => (x.id === d.id ? { ...x, ...d } : x)) } : l));
                  void load(); // counts per status, and the filters may no longer match
                }} />
            ))}
          </ul>
        </>
      )}
    </>
  );
}
