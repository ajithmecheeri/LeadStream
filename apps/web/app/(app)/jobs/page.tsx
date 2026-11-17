"use client";
import type { JobList, JobStats, MatchingStatus, UserJob } from "@fitfirst/api";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { PulledJobs } from "@/components/PulledJobs";
import { errorMessage, Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { APPLICATION_STATUS, applyLink, BAND, DEFAULT_FILTERS, factsLine, filtersFromSearch, filtersToSearch, inQueue, isMatchTab, jobQuery, LEAD_LABEL, matchLine, seenAgo, sourceLabels, TABS, unverifiedNote, type JobFilters, type Tab } from "@/lib/jobs";

const TAB_EMPTY: Record<Tab, string> = {
  top: "No strong or good matches here yet.",
  other: "Nothing in Other jobs.",
  unscored: "Every job has a score.",
  applied: "Nothing marked Applied yet. Use Applied on a job after you apply on the portal.",
  expired: "No expired jobs.",
  ignored: "Nothing ignored.",
  all: "No jobs match these filters.",
  sources: "",
  review: "Nothing to review. Jobs you add from Google results with the BrewMyJob extension wait here.",
};

/** Jobs → From sources: every job the job sources brought you, the last run first and then older ones; the ones
 *  that fit are in your list already, the others say why they were left out and can be added (user, 2026-11-16,
 *  2026-11-17). */
function FromSources() {
  const [ranAt, setRanAt] = useState<string | null>(null);
  return (
    <section className="card" style={{ marginTop: 12 }} data-testid="from-sources">
      <div className="card-head">
        <h2>Jobs from the job sources</h2>
        {ranAt ? <span className="subtle">Last run {new Date(ranAt).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} ({seenAgo(ranAt)})</span> : null}
      </div>
      <p className="hint">
        Open jobs at the companies BrewMyJob reads and from job sites. The ones that fit your profile are already in
        your jobs (Top matches or Other jobs); add any other one to score it.
      </p>
      <PulledJobs
        newLabel="Found at the last run"
        load={() =>
          api.sourceJobs().then((r) => {
            setRanAt(r.ran_at ?? null);
            return r.items;
          })
        }
        add={api.addSourceJob}
        empty="No jobs from the job sources yet. They arrive within a few hours of adding your resume."
      />
    </section>
  );
}

function MatchScore({ job }: { job: UserJob }) {
  const m = job.match;
  if (!m) return <div className="score score-none" title="Not scored yet">–</div>;
  const band = BAND[m.band];
  return (
    <div className={`score score-${band.kind}`} data-testid="match-score" title={band.label}>
      {m.score}%
    </div>
  );
}

const PAGE = 25;

/** Where to apply for a job in the list: the company's careers page first, then the portals. */
const apply = (j: UserJob) => applyLink(j.job.sources, j.job.company);

export default function JobsPage() {
  const [filters, setFilters] = useState<JobFilters | null>(null);
  const [q, setQ] = useState("");
  const [list, setList] = useState<JobList | null>(null);
  const [stats, setStats] = useState<JobStats | null>(null);
  const [matching, setMatching] = useState<MatchingStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // Filters live in the URL, so Back from a job returns to the same list.
  useEffect(() => {
    const f = filtersFromSearch(window.location.search);
    setFilters(f);
    setQ(f.q);
  }, []);

  const load = useCallback(async (f: JobFilters, offset = 0) => {
    setError(null);
    try {
      const page = await api.jobs({ ...jobQuery(f), limit: PAGE, offset });
      setList((cur) => (offset && cur ? { ...page, items: [...cur.items, ...page.items] } : page));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  const loadCounts = useCallback(async () => {
    try {
      const [s, m] = await Promise.all([api.jobStats(), api.matchingStatus()]);
      setStats(s);
      setMatching(m);
      return m;
    } catch {
      return null; // the list shows its own error
    }
  }, []);

  useEffect(() => {
    if (!filters) return;
    window.history.replaceState(null, "", `/jobs${filtersToSearch(filters)}`);
    if (filters.tab !== "sources") void load(filters);
    void loadCounts();
  }, [filters, load, loadCounts]);

  // While a scoring run is queued or running, check every few seconds and refresh the list when it ends.
  useEffect(() => {
    if (!matching?.scoring || !filters) return;
    const t = setTimeout(async () => {
      const m = await loadCounts();
      if (m && !m.scoring) void load(filters);
    }, 3000);
    return () => clearTimeout(t);
  }, [matching, filters, load, loadCounts]);

  // Search as you type, after a short pause.
  useEffect(() => {
    const t = setTimeout(() => setFilters((f) => (f && f.q !== q ? { ...f, q } : f)), 300);
    return () => clearTimeout(t);
  }, [q]);

  const set = <K extends keyof JobFilters>(k: K, v: JobFilters[K]) => setFilters((f) => (f ? { ...f, [k]: v } : f));

  async function setStatus(job: UserJob, status: UserJob["status"]) {
    setBusy(job.id);
    try {
      const updated = await api.setJobStatus(job.id, status, job.version);
      setList((cur) => {
        if (!cur || !filters) return cur;
        return inQueue(filters.tab, updated.status)
          ? {
              ...cur,
              items: cur.items.map((j) =>
                j.id === job.id
                  ? {
                      ...j,
                      status: updated.status,
                      version: updated.version,
                      expired_by: updated.expired_by,
                      may_have_expired: updated.may_have_expired,
                      todo: updated.todo,
                      application: updated.application,
                    }
                  : j,
              ),
            }
          : { ...cur, total: cur.total - 1, items: cur.items.filter((j) => j.id !== job.id) };
      });
      void loadCounts();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  if (!filters) return <div className="loading">Loading…</div>;
  const filtered = filtersToSearch({ ...filters, status: DEFAULT_FILTERS.status, tab: DEFAULT_FILTERS.tab }) !== "";
  const counts: Partial<Record<Tab, number>> = stats
    ? {
        top: stats.top,
        other: stats.other,
        unscored: stats.unscored,
        applied: stats.applied,
        expired: stats.expired,
        ignored: stats.ignored,
        review: stats.review,
        all: stats.active + stats.applied + stats.expired + stats.ignored + stats.review,
      }
    : {};
  const noResume = matching !== null && matching.resumes === 0;

  return (
    <>
      <PageHeader
        title="Jobs"
        sub="Every job from the alerts you forward, scored against your resumes. Best matches first."
        actions={
          <>
            <Link className="btn btn-sm" href="/jobs/find">Find on Google</Link>
            <Link className="btn btn-sm" href="/inbox">Inbox</Link>
          </>
        }
      />
      {noResume ? (
        <div style={{ marginBottom: 12 }}>
          <Notice kind="info">
            Add your resume to see match scores and your best matches first. <Link href="/profile">Add a resume</Link>
          </Notice>
        </div>
      ) : matching?.scoring ? (
        <div style={{ marginBottom: 12 }} data-testid="scoring-banner">
          <Notice kind="info">Scoring your jobs… this page updates when it&apos;s done.</Notice>
        </div>
      ) : null}
      <div className="tabs" role="group" aria-label="Queue">
        {TABS.filter((t) => (t.value !== "unscored" && t.value !== "review") || (counts[t.value] ?? 0) > 0 || filters.tab === t.value).map((t) => (
          <button key={t.value} type="button" aria-pressed={filters.tab === t.value} onClick={() => setFilters((f) => (f ? { ...f, tab: t.value, readiness: t.value === "top" ? f.readiness : "" } : f))}>
            {t.label}
            {counts[t.value] !== undefined ? <span className="count">{counts[t.value]}</span> : null}
          </button>
        ))}
      </div>
      {filters.tab === "sources" ? <FromSources /> : (<>
      <section className="card filters" aria-label="Filters">
        {isMatchTab(filters.tab) ? (
          <label className="check">
            <input type="checkbox" checked={filters.status === "new"} onChange={(e) => set("status", e.target.checked ? "new" : "active")} />
            New only
          </label>
        ) : null}
        <input className="input grow" type="search" aria-label="Search jobs" placeholder="Search title, company, location or skill"
          value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="select narrow" aria-label="Source" value={filters.source} onChange={(e) => set("source", e.target.value as JobFilters["source"])}>
          <option value="">All sources</option>
          <option value="linkedin">LinkedIn</option>
          <option value="naukri">Naukri</option>
          <option value="foundit">Foundit</option>
          <option value="company">Company careers</option>
          <option value="adzuna">Adzuna</option>
          <option value="assistant">AI assistant</option>
        </select>
        <select className="select narrow" aria-label="Lead" value={filters.lead} onChange={(e) => set("lead", e.target.value as JobFilters["lead"])}>
          <option value="">All kinds</option>
          <option value="alert">Job alerts</option>
          <option value="recommendation">Recommended</option>
          <option value="recruiter_invite">Recruiter invites</option>
          <option value="company_feed">Company careers</option>
          <option value="job_board">Job boards</option>
        </select>
        {filters.tab === "top" ? (
          <select className="select narrow" aria-label="Readiness" value={filters.readiness} onChange={(e) => set("readiness", e.target.value as JobFilters["readiness"])}>
            <option value="">Ready or not</option>
            <option value="ready">Ready to apply</option>
            <option value="needs_input">Needs your input</option>
          </select>
        ) : null}
        <select className="select narrow" aria-label="First seen" value={filters.range} onChange={(e) => set("range", e.target.value as JobFilters["range"])}>
          <option value="any">Any time</option>
          <option value="today">Today</option>
          <option value="7d">Last 7 days</option>
          <option value="30d">Last 30 days</option>
          <option value="custom">Dates…</option>
        </select>
        {filters.range === "custom" ? (
          <>
            <input className="input narrow" type="date" aria-label="From" value={filters.from} onChange={(e) => set("from", e.target.value)} />
            <input className="input narrow" type="date" aria-label="To" value={filters.to} onChange={(e) => set("to", e.target.value)} />
          </>
        ) : null}
        {filtered ? (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setQ(""); setFilters({ ...DEFAULT_FILTERS, status: filters.status, tab: filters.tab }); }}>
            Clear filters
          </button>
        ) : null}
      </section>

      {error ? <div style={{ margin: "16px 0" }}><Notice kind="bad">{error}</Notice></div> : null}
      {!list ? (
        <div className="loading">Loading…</div>
      ) : list.items.length === 0 ? (
        <section className="card empty">
          {filtered ? (
            <p className="muted">No jobs match these filters.</p>
          ) : filters.tab !== "all" && (stats?.active ?? 0) > 0 ? (
            <p className="muted">
              {TAB_EMPTY[filters.tab]}{" "}
              {noResume ? <Link href="/profile">Add a resume</Link> : null}
            </p>
          ) : (
            <>
              <h2>No jobs yet</h2>
              <p className="muted">
                Jobs appear here when LinkedIn or Naukri alert emails reach your BrewMyJob address.{" "}
                <Link href="/settings/mail">Set up forwarding</Link>.
              </p>
            </>
          )}
        </section>
      ) : (
        <>
          <p className="subtle" style={{ margin: "14px 2px 8px" }} data-testid="jobs-total">
            {list.total} job{list.total === 1 ? "" : "s"}
          </p>
          <ul className="job-list">
            {list.items.map((j) => (
              <li key={j.id} className={`card job-card ${j.status}`} data-testid="job-card">
                <MatchScore job={j} />
                <div className="job-main">
                  <div className="row">
                    <Link className="job-title" href={`/jobs/${j.id}`}>{j.job.title}</Link>
                    {j.status === "new" ? <span className="badge badge-good">New</span> : null}
                    {j.status === "ignored" ? <span className="badge">Ignored</span> : null}
                    {j.status === "review" ? <span className="badge badge-warn">To review</span> : null}
                    {j.status === "expired" ? (
                      <span className="badge">{j.expired_by === "auto" ? "Expired (no recent alert)" : "Expired"}</span>
                    ) : null}
                    {j.application ? (
                      <span className={`badge badge-${APPLICATION_STATUS[j.application.status]?.kind || "plain"}`} data-testid="application-status">
                        {APPLICATION_STATUS[j.application.status]?.label ?? j.application.status}
                      </span>
                    ) : null}
                    {j.may_have_expired ? <span className="badge badge-warn">May have expired</span> : null}
                    {sourceLabels(j.job.sources, j.job.company).map((label) => (
                      <span key={label} className="badge badge-info" title="Where this job came from" data-testid="job-source">{label}</span>
                    ))}
                    {j.todo > 0 ? (
                      <Link className="badge badge-warn" href={`/jobs/${j.id}#todo`} data-testid="todo-count">
                        {j.todo} to do
                      </Link>
                    ) : null}
                    {j.lead === "recruiter_invite" ? <span className="badge badge-warn">Recruiter invite</span> : null}
                    {!j.job.verified ? <span className="badge" title={unverifiedNote(j.job) ?? undefined} data-testid="unverified-badge">Unverified</span> : null}
                    {j.possible_duplicate ? (
                      <Link className="badge badge-warn" href={`/jobs/${j.id}`} data-testid="possible-duplicate-badge" title="Possibly the same role as another of your jobs: decide on its page">
                        Possible duplicate
                      </Link>
                    ) : null}
                    {j.readiness && isMatchTab(filters.tab) ? (
                      j.readiness.status === "ready"
                        ? <span className="badge badge-good" data-testid="readiness">Ready</span>
                        : <span className="badge" data-testid="readiness">Needs input ({j.readiness.blockers})</span>
                    ) : null}
                  </div>
                  <div className="muted">{j.job.company ?? "Company not named"}</div>
                  <div className="subtle">{factsLine(j.job)}</div>
                  <div className="row subtle">
                    <span>{seenAgo(j.first_seen_at)}</span>
                    <span>·</span>
                    <span>{LEAD_LABEL[j.lead]}</span>
                    {j.outside_preference ? <span title="The portal marked this outside your saved preferences">· Outside your preference</span> : null}
                  </div>
                  {j.match ? (
                    <div className="match-line" data-testid="match-line">
                      {j.match.band === "filtered" ? (
                        <span>Ruled out: {j.match.filter_reason}</span>
                      ) : (
                        <span>{matchLine(j.match)}</span>
                      )}
                      {j.match.provisional ? <span className="subtle" title="Scored from the alert's few facts. Paste the full description on the job to refine it."> · from the alert</span> : null}
                    </div>
                  ) : null}
                </div>
                <div className="job-actions">
                  {j.status === "new" || j.status === "seen" ? (
                    <>
                      {apply(j) ? (
                        <a className="btn btn-sm btn-primary" href={apply(j)!.href} target="_blank" rel="noopener noreferrer"
                          title={apply(j)!.label} aria-label={apply(j)!.label} data-testid="apply-link">
                          Apply ↗
                        </a>
                      ) : null}
                      <button className="btn btn-sm" disabled={busy === j.id} onClick={() => setStatus(j, "applied")}
                        aria-label={`Mark ${j.job.title} as applied`} title="You applied on the portal: track it here">Applied</button>
                      <button className="btn btn-sm btn-ghost" disabled={busy === j.id} onClick={() => setStatus(j, "ignored")}
                        aria-label={`Ignore ${j.job.title}`}>Ignore</button>
                      <button className="btn btn-sm btn-ghost" disabled={busy === j.id} onClick={() => setStatus(j, "expired")}
                        aria-label={`Mark ${j.job.title} as expired`} title="The posting has closed">Expired</button>
                    </>
                  ) : j.status === "review" ? (
                    <>
                      {apply(j) ? (
                        <a className="btn btn-sm" href={apply(j)!.href} target="_blank" rel="noopener noreferrer"
                          title={apply(j)!.label} aria-label={apply(j)!.label} data-testid="apply-link">
                          Apply ↗
                        </a>
                      ) : null}
                      <button className="btn btn-sm btn-primary" disabled={busy === j.id} onClick={() => setStatus(j, "seen")}
                        aria-label={`Keep ${j.job.title}`} title="Move it to your jobs: Top matches or Other jobs by its score">Keep</button>
                      <Link className="btn btn-sm" href={`/jobs/${j.id}`} title="Paste the full description for a full score">Add description</Link>
                      <button className="btn btn-sm btn-ghost" disabled={busy === j.id} onClick={() => setStatus(j, "ignored")}
                        aria-label={`Ignore ${j.job.title}`}>Ignore</button>
                    </>
                  ) : j.status === "applied" ? (
                    <Link className="btn btn-sm" href={`/applications?open=${j.application?.id ?? ""}`}>Track</Link>
                  ) : (
                    <button className="btn btn-sm" disabled={busy === j.id} onClick={() => setStatus(j, "seen")}>Restore</button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {list.items.length < list.total ? (
            <div className="row" style={{ justifyContent: "center", marginTop: 16 }}>
              <button className="btn" onClick={() => load(filters, list.items.length)}>Show more</button>
            </div>
          ) : null}
        </>
      )}
      </>)}
    </>
  );
}
