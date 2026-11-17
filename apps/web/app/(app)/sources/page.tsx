"use client";
import type { FollowedCompany, FoundBoard, Sources } from "@fitfirst/api";
import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { PulledJobs } from "@/components/PulledJobs";
import { errorMessage, Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { seenAgo } from "@/lib/jobs";
import { useSession } from "@/lib/session";

const ATS_LABEL: Record<string, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  smartrecruiters: "SmartRecruiters",
  workday: "Workday",
  oracle: "Oracle Recruiting",
  eightfold: "Eightfold",
  careers_page: "its careers site",
};

/** A company name from a board found by its link: "acme" → "Acme"; "nvidia.wd5.myworkdayjobs.com/…" → "Nvidia";
 *  "careers.arm.com" → "Arm"; Eightfold's "explore.jobs.netflix.net/netflix.com" → "Netflix". */
function nameFromBoard(ats: string, board: string): string {
  let id = board;
  if (ats === "eightfold") id = (board.split("/")[1] || board).split(".")[0]!;
  else if (ats === "careers_page") {
    const labels = board.split("/")[0]!.split(".");
    id = labels.length >= 2 ? labels[labels.length - 2]! : labels[0]!;
  } else if (ats === "workday" || ats === "oracle") id = board.split(".")[0]!;
  return id.charAt(0).toUpperCase() + id.slice(1);
}

function runLine(c: FollowedCompany): string {
  if (!c.last_run) return c.last_checked_at ? "Checked for another user; yours runs next" : "Checking soon…";
  const r = c.last_run;
  if (r.error) return r.error;
  const parts = [`${c.jobs_india ?? r.found} open in India`, `${c.my_jobs} in your list`, `${r.added} added at the last check`];
  if (r.skipped) parts.push(`${r.skipped} left out then (other level or field)`);
  return `${parts.join(" · ")} · checked ${seenAgo(r.ran_at)}`;
}

/** Find a company's board by name or link, then follow the right one. */
function AddCompany({ onAdded }: { onAdded: () => void }) {
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<FoundBoard[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function search(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setFound(null);
    try {
      setFound(await api.lookupCompany(query.trim()));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function follow(f: FoundBoard) {
    setBusy(true);
    setError(null);
    try {
      const name = query.includes("/") ? nameFromBoard(f.ats, f.board) : query.trim();
      await api.followCompany({ name, ats: f.ats, board: f.board });
      setQuery("");
      setFound(null);
      onAdded();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack-tight">
      <form className="row" onSubmit={search}>
        <input
          className="input"
          aria-label="Company name or careers-page link"
          placeholder="Company name, or a link to its careers site"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ flex: 1, minWidth: 220 }}
        />
        <button className="btn" disabled={busy || query.trim().length < 2}>{busy && !found ? "Searching…" : "Find"}</button>
      </form>
      {error ? <Notice kind="bad">{error}</Notice> : null}
      {found && found.length === 0 ? (
        <p className="hint">
          Nothing found by that name on Greenhouse, Lever, Ashby or SmartRecruiters. Paste the link of the
          company&apos;s careers site instead: sites on Workday, Oracle, Eightfold or SuccessFactors, and companies&apos;
          own careers sites, are found by their link. Job portals such as LinkedIn or Naukri can&apos;t be followed;
          their jobs reach you through alert emails.
        </p>
      ) : null}
      {found && found.length > 0 ? (
        <ul className="stack-tight" data-testid="found-boards">
          {found.map((f) => (
            <li key={`${f.ats}:${f.board}`} className="row">
              <span>
                <strong>{f.board}</strong> on {ATS_LABEL[f.ats]} ·{" "}
                {f.ats === "careers_page" ? `${f.total} job pages · ${f.india} in India in a first look` : `${f.india} in India of ${f.total}`}
                {f.sample.length ? <span className="subtle"> · e.g. {f.sample.join(", ")}</span> : null}
              </span>
              <span className="spacer" />
              <a className="btn btn-sm btn-ghost" href={f.board_url} target="_blank" rel="noopener noreferrer">View</a>
              <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => follow(f)}>Follow</button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** A time on the user's clock (Settings → Time zone), with the zone's short name: "5 Nov, 06:30 pm IST". */
const localTime = (iso: string, timeZone: string) =>
  new Date(iso).toLocaleString("en-IN", { timeZone, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Every job the last run brought for you, kept or not (user, 2026-11-16). */
const lastRunJobs =() => api.lastRunJobs().then((r) => r.items);
const NO_RUN_JOBS = "No jobs listed for this run. Runs from 16 Nov list every job they bring for you, including the ones left out.";

/** A followed company's open India jobs: which its last check found, which are in your list, and why the others
 *  were left out (user, 2026-11-16: "when I click on 22 jobs, it does not say which are those jobs"). */
function CompanyJobs({ company }: { company: FollowedCompany }) {
  return (
    <PulledJobs
      testId="company-jobs"
      load={() => api.companyJobs(company.id).then((r) => r.items)}
      add={(jobId) => api.addCompanyJob(company.id, jobId)}
      empty={`No open jobs in India at ${company.name} right now.`}
    />
  );
}

function LastRun({ data, timeZone }: { data: Sources; timeZone: string }) {
  const run = data.last_run;
  const [open, setOpen] = useState(false);
  return (
    <section className="card" data-testid="last-run">
      <div className="card-head">
        <h2>Last run</h2>
        {run ? <span className="subtle">{localTime(run.ran_at, timeZone)} ({seenAgo(run.ran_at)})</span> : null}
      </div>
      {run ? (
        <>
          <div className="stat-row">
            <div className="stat" data-testid="last-run-jobs">
              <b>{run.jobs}</b>
              <span className="subtle">jobs pulled ({run.new} new, {run.updated} updated)</span>
            </div>
            <div className="stat" data-testid="last-run-fit">
              <b>{run.fit}</b>
              <span className="subtle">fit your profile</span>
            </div>
            <div className="stat" data-testid="last-run-added">
              <b>{run.added ? <Link href="/jobs?tab=all">{run.added}</Link> : 0}</b>
              <span className="subtle">new in your list</span>
            </div>
            <div className="stat" data-testid="last-run-top">
              <b>{run.top_matches ? <Link href="/jobs?tab=top">{run.top_matches}</Link> : 0}</b>
              <span className="subtle">Top matches</span>
            </div>
          </div>
          <p className="hint" style={{ marginTop: 8 }}>
            Jobs pulled from every company board and job API BrewMyJob reads
            {run.closed ? `; ${plural(run.closed, "job")} taken down by the employer` : ""}. They fit your profile when
            they come from a company you follow, or a job API, at your level and in your field.
          </p>
          <button type="button" className="btn btn-sm" style={{ marginTop: 8 }} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? "Hide the jobs" : "See every job from this run"}
          </button>
          {open ? <PulledJobs load={lastRunJobs} add={api.addRunJob} empty={NO_RUN_JOBS} /> : null}
        </>
      ) : (
        <p className="subtle">No jobs pulled yet. Runs happen {data.check_times}.</p>
      )}
    </section>
  );
}

/** What the latest check pulled, across every source, and when the next one runs. */
function LastCheck({ data, timeZone }: { data: Sources; timeZone: string }) {
  const last = data.last_check;
  const at = (iso: string) => localTime(iso, timeZone);
  return (
    <section className="card" data-testid="last-check">
      <div className="card-head">
        <h2>Your last check</h2>
        <span className="subtle">Companies are read {data.check_times}</span>
      </div>
      {last ? (
        <div className="row" style={{ gap: 24, flexWrap: "wrap" }}>
          <div className="stack-tight">
            <strong className="num" data-testid="last-check-added">
              {last.added ? <Link href="/jobs?tab=all">{last.added} new job{last.added === 1 ? "" : "s"} for you</Link> : "No new jobs for you"}
            </strong>
            <span className="subtle">{at(last.ran_at)} ({seenAgo(last.ran_at)})</span>
          </div>
          <div className="stack-tight">
            <span><strong className="num">{last.found}</strong> India jobs listed by {last.sources} source{last.sources === 1 ? "" : "s"}</span>
            <span className="subtle">
              {last.skipped} not shown (other level or field)
              {last.errors ? <span className="field-error"> · {last.errors} couldn&apos;t be read</span> : null}
            </span>
          </div>
        </div>
      ) : (
        <p className="subtle">Not checked yet. Follow a company below, or press Check now.</p>
      )}
    </section>
  );
}

export default function SourcesPage() {
  const { me } = useSession();
  const [data, setData] = useState<Sources | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [openCompany, setOpenCompany] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.sources());
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // While a check runs in the background, refresh every few seconds.
  useEffect(() => {
    if (!data?.checking) return;
    const t = setTimeout(() => void load(), 4000);
    return () => clearTimeout(t);
  }, [data, load]);

  async function act(fn: () => Promise<unknown>, done?: string) {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      await fn();
      if (done) setNote(done);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <div className="loading">{error ?? "Loading…"}</div>;
  const toFollow = data.suggestions.filter((s) => !s.watching);

  return (
    <div className="stack">
      <PageHeader
        title="Job sources"
        sub="Where your jobs come from besides alert emails. Every source here is a public feed meant for sharing jobs; BrewMyJob never logs in to a job site."
        actions={
          <button className="btn btn-sm" disabled={busy || data.checking} onClick={() => act(() => api.checkSources(), "Checking now. New jobs appear on the Jobs page in a minute or two.")}>
            {data.checking ? "Checking…" : "Check now"}
          </button>
        }
      />
      {error ? <Notice kind="bad">{error}</Notice> : null}
      {note ? <Notice kind="good">{note}</Notice> : null}
      {!data.service_available ? (
        <Notice kind="bad">
          Job search can&apos;t be reached right now, so company details and new jobs are on hold. Your list of
          companies is safe; this page fills in again once it&apos;s back.
        </Notice>
      ) : null}

      <LastRun data={data} timeZone={me?.timezone ?? "Asia/Kolkata"} />
      <LastCheck data={data} timeZone={me?.timezone ?? "Asia/Kolkata"} />

      <section className="card">
        <div className="card-head">
          <h2>Company career pages</h2>
          <span className="subtle">Read {data.check_times.replace(/ \(.*\)$/, "")} · India jobs at or near your level</span>
        </div>
        <AddCompany onAdded={() => void load()} />
        {data.companies.length ? (
          <ul className="stack-tight" style={{ marginTop: 12 }} data-testid="companies">
            {data.companies.map((c) => (
              <li key={c.id} data-testid="company">
                <div className="row">
                  <span>
                    <strong>{c.name}</strong> {c.ats ? <span className="subtle">on {ATS_LABEL[c.ats]}</span> : null}
                    <br />
                    <span className={c.last_run?.error ? "field-error" : "subtle"}>{runLine(c)}</span>
                  </span>
                  <span className="spacer" />
                  <button type="button" className="btn btn-sm" aria-expanded={openCompany === c.id} data-testid="company-jobs-toggle"
                    onClick={() => setOpenCompany((o) => (o === c.id ? null : c.id))}>
                    {openCompany === c.id ? "Hide jobs" : c.jobs_india ? `See the ${c.jobs_india} job${c.jobs_india === 1 ? "" : "s"}` : "See jobs"}
                  </button>
                  {c.board_url ? <a className="btn btn-sm btn-ghost" href={c.board_url} target="_blank" rel="noopener noreferrer">Careers page</a> : null}
                  <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => act(() => api.unfollowCompany(c.id))}>Unfollow</button>
                </div>
                {openCompany === c.id ? <CompanyJobs company={c} /> : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="hint" style={{ marginTop: 12 }}>You don&apos;t follow any company yet. Find one above, or start with the suggestions below.</p>
        )}
      </section>

      {toFollow.length ? (
        <section className="card" data-testid="suggestions">
          <div className="card-head">
            <h2>Suggested companies</h2>
            <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => act(() => api.followSuggested(toFollow.map((s) => `${s.ats}:${s.board}`)), "Following them. Their jobs arrive in a minute or two.")}>
              Follow all {toFollow.length}
            </button>
          </div>
          <p className="hint">Companies with public job feeds and senior openings in India (checked November 2026).</p>
          <div className="chips" style={{ marginTop: 8 }}>
            {toFollow.map((s) => (
              <button key={`${s.ats}:${s.board}`} className="chip" disabled={busy} onClick={() => act(() => api.followSuggested([`${s.ats}:${s.board}`]))}>
                + {s.name}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      <section className="card" data-testid="adzuna">
        <div className="card-head">
          <h2>Adzuna</h2>
          <span className="subtle">Listings gathered from many Indian job sites</span>
        </div>
        {!data.adzuna.configured ? (
          <p className="hint">
            Not connected yet. Get a free key at developer.adzuna.com and put <code>ADZUNA_APP_ID</code> and{" "}
            <code>ADZUNA_APP_KEY</code> in the app&apos;s <code>.env</code>.
          </p>
        ) : !data.adzuna.searches.length ? (
          <p className="hint">Adzuna searches with your search profiles. <Link href="/profile">Add a resume</Link> to start: its Skill Match profile is made from it.</p>
        ) : (
          <>
            <p className="hint">Searches: {data.adzuna.searches.join(" · ")}</p>
            {data.adzuna.last_run ? (
              <p className={data.adzuna.last_run.error ? "field-error" : "subtle"}>
                {data.adzuna.last_run.error ??
                  `${data.adzuna.last_run.found} found · ${data.adzuna.last_run.added} new for you · ${data.adzuna.last_run.skipped} not shown · checked ${seenAgo(data.adzuna.last_run.ran_at)}`}
              </p>
            ) : (
              <p className="subtle">Not checked yet. Press Check now.</p>
            )}
          </>
        )}
      </section>

      {data.connectors.some((c) => c.boards || c.runs_24h) ? (
        <section className="card" data-testid="connectors">
          <div className="card-head">
            <h2>Hiring systems</h2>
            <span className="subtle">Last 24 hours, for everyone who uses BrewMyJob</span>
          </div>
          <ul className="stack-tight">
            {data.connectors.filter((c) => c.boards || c.runs_24h).map((c) => (
              <li key={c.connector} className="row">
                <strong>{ATS_LABEL[c.connector] ?? (c.connector === "adzuna" ? "Adzuna" : c.connector)}</strong>
                <span className="subtle">
                  {c.boards ? `${c.boards} compan${c.boards === 1 ? "y" : "ies"} · ` : ""}
                  {c.runs_24h} read{c.runs_24h === 1 ? "" : "s"}
                  {c.failures_24h ? <span className="field-error"> · {c.failures_24h} failed{c.last_error ? `: ${c.last_error}` : ""}</span> : null}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="card">
        <div className="card-head"><h2>Alert emails</h2></div>
        <p className="hint">LinkedIn and Naukri alerts forwarded from Gmail. <Link href="/settings/mail">Mail setup</Link></p>
      </section>
    </div>
  );
}
