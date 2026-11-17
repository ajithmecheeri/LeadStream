"use client";
import type { RunJob } from "@fitfirst/api";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { errorMessage, Notice } from "@/components/ui";

/** A job a job source brought: in your list, or left out and why. `job_id` is null while the job is still on its
 *  way to BrewMyJob's catalog; `new` marks the ones a company's last check found. */
export type PulledJob = Omit<RunJob, "job_id"> & { job_id?: string | null; new?: boolean };

type Show = "all" | "in" | "out";

/** Jobs from the job sources, kept or not (user, 2026-11-16), with filters and "Add to my jobs" for the ones left
 *  out. Used by Jobs → From sources, Job sources → Last run, and each followed company. */
export function PulledJobs({
  load,
  add,
  empty,
  caption,
  testId = "run-jobs",
  newLabel = "Found at the last check",
}: {
  load: () => Promise<PulledJob[]>;
  add: (jobId: string) => Promise<RunJob>;
  empty: ReactNode;
  caption?: ReactNode;
  testId?: string;
  newLabel?: string;
}) {
  const [items, setItems] = useState<PulledJob[] | null>(null);
  const [show, setShow] = useState<Show>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    load().then(setItems).catch((e) => setError(errorMessage(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loaded once per mount
  }, []);

  async function addOne(jobId: string) {
    setBusy(jobId);
    setError(null);
    try {
      const added = await add(jobId);
      setItems((list) => (list ? list.map((i) => (i.job_id === jobId ? { ...added, new: i.new } : i)) : list));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  if (error && !items) return <Notice kind="bad">{error}</Notice>;
  if (!items) return <p className="subtle" style={{ marginTop: 12 }}>Loading…</p>;
  if (!items.length) return <div className="subtle" style={{ marginTop: 12 }} data-testid={testId}>{empty}</div>;
  // A company's list (items carry `new`) shows the jobs its last check found in their own section first, and the
  // other open jobs below (user, 2026-11-16: "show the jobs in last run separate").
  const hasNew = items.some((i) => i.new !== undefined);
  const fresh = hasNew ? items.filter((i) => i.new) : [];
  const rest = hasNew ? items.filter((i) => !i.new) : items;
  const kept = rest.filter((i) => i.in_list).length;
  const shown = rest.filter((i) => (show === "all" ? true : (show === "in") === i.in_list));
  const filters: { value: Show; label: string }[] = [
    { value: "all", label: `All (${rest.length})` },
    { value: "in", label: `In your list (${kept})` },
    { value: "out", label: `Left out (${rest.length - kept})` },
  ];
  const rows = (list: PulledJob[]) => (
    <ul className="doc-list">
      {list.map((i, n) => (
        <li key={i.job_id ?? `${i.title}-${n}`} data-testid="run-job">
          <div className="grow stack-tight" style={{ minWidth: 0 }}>
            <span>
              {i.user_job_id ? <Link href={`/jobs/${i.user_job_id}`}><strong>{i.title}</strong></Link> : <strong>{i.title}</strong>}
              {i.new ? <span className="badge badge-info" style={{ marginLeft: 8 }}>New</span> : null}
            </span>
            <span className="subtle">
              {[i.company, i.location].filter(Boolean).join(" · ")}
              {i.in_list ? (i.score !== null && i.score !== undefined ? ` · ${i.score}% match` : " · scoring…") : ""}
            </span>
            {!i.in_list && i.why ? <span className="subtle" data-testid="run-job-why">Left out: {i.why}</span> : null}
          </div>
          {i.url ? <a className="btn btn-sm btn-ghost" href={i.url} target="_blank" rel="noopener noreferrer">Posting ↗</a> : null}
          {i.in_list ? <span className="badge badge-good">In your list</span> : i.job_id ? (
            <button type="button" className="btn btn-sm" disabled={busy !== null} onClick={() => void addOne(i.job_id!)}>
              {busy === i.job_id ? "Adding…" : "Add to my jobs"}
            </button>
          ) : (
            <span className="subtle" title="It reaches BrewMyJob within a few minutes">Arriving…</span>
          )}
        </li>
      ))}
    </ul>
  );
  return (
    <div className="stack-tight" style={{ marginTop: 12 }} data-testid={testId}>
      {caption ? <p className="subtle">{caption}</p> : null}
      {error ? <Notice kind="bad">{error}</Notice> : null}
      {hasNew ? (
        <div className="stack-tight" data-testid="last-check-jobs">
          <h3 style={{ margin: 0 }}>{newLabel} ({fresh.length})</h3>
          {fresh.length ? rows(fresh) : <p className="subtle">Nothing new then.</p>}
          <h3 style={{ margin: "12px 0 0" }}>Other open jobs ({rest.length})</h3>
        </div>
      ) : null}
      <div className="row" role="group" aria-label="Show">
        {filters.map((f) => (
          <button key={f.value} type="button" className={`btn btn-sm ${show === f.value ? "btn-primary" : "btn-ghost"}`}
            aria-pressed={show === f.value} onClick={() => setShow(f.value)}>{f.label}</button>
        ))}
      </div>
      {!shown.length ? <p className="subtle">No jobs here.</p> : rows(shown)}
    </div>
  );
}
