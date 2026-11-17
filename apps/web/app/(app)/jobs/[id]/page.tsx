"use client";
import type { ContactIn, ContactList, JobPeople, MatchDetail, ResumeComparison, Todo, UserJobDetail } from "@fitfirst/api";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useEffect, useState, type FormEvent } from "react";
import { ApplyKit } from "@/components/ApplyKit";
import { NotForMe, reasonLabel } from "@/components/NotForMe";
import { errorMessage, Field, fieldErrors, Notice, PageHeader, toStrOrNull } from "@/components/ui";
import { api } from "@/lib/api";
import { downloadBlob } from "@/lib/documents";
import { APPLICATION_STATUS, applyLink, BAND, isNaukriSignInLink, factsLine, LEAD_LABEL, seenAgo, sourceLabel, sourceLabels, unverifiedNote } from "@/lib/jobs";

function Bar({ value }: { value: number }) {
  return (
    <span className="bar" aria-hidden="true">
      <span style={{ width: `${Math.max(2, Math.min(100, value))}%` }} />
    </span>
  );
}

type Pair = UserJobDetail["duplicates"][number];

const shortDate = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

/** The two jobs side by side, to decide whether they are one role. */
function CompareJobs({ job, pair }: { job: UserJobDetail; pair: Pair }) {
  const a = job.job;
  const b = pair.other.job;
  const rows: [string, string | null | undefined, string | null | undefined][] = [
    ["Title", a.title, b.title],
    ["Company", a.company, b.company],
    ["Location", a.location, b.location],
    ["Experience", a.experience, b.experience],
    ["Salary", a.salary, b.salary],
    ["Listed on", sourceLabels(a.sources, a.company).join(", "), sourceLabels(b.sources, b.company).join(", ")],
    ["First seen", shortDate(job.first_seen_at), shortDate(pair.other.first_seen_at)],
  ];
  return (
    <div className="compare" data-testid="duplicate-compare">
      <table className="compare-table side">
        <thead>
          <tr><th /><th>This job</th><th><Link href={`/jobs/${pair.other.id}`}>The other job</Link></th></tr>
        </thead>
        <tbody>
          {rows.map(([label, x, y]) => (
            <tr key={label}>
              <td>{label}</td>
              <td className={x !== y ? "differs" : undefined}>{x || "—"}</td>
              <td className={x !== y ? "differs" : undefined}>{y || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="subtle" style={{ marginTop: 8 }}>
        {pair.similarity === null
          ? "One of them has no description to compare."
          : `The descriptions are ${pair.similarity}% alike.`}
      </p>
    </div>
  );
}

/**
 * Duplicates (milestone 9.3): a job merged into another, jobs merged into this one ("Also seen as"), and possible
 * duplicates in amber with Same job / Different job. Nothing is merged on a guess.
 */
function Duplicates({ job, onJob }: { job: UserJobDetail; onJob: (j: UserJobDetail) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  if (!job.duplicates.length) return null;

  async function answer(pair: Pair, same: boolean) {
    setBusy(true);
    setError(null);
    try {
      onJob(await api.answerDuplicate(job.id, pair.id, same));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const name = (p: Pair) => `${p.other.job.title}${p.other.job.company ? ` at ${p.other.job.company}` : ""}`;
  const via = (p: Pair) => sourceLabels(p.other.job.sources, p.other.job.company).join(", ");
  const into = job.duplicates.find((p) => p.merged === "into_other");
  const also = job.duplicates.filter((p) => p.merged === "into_this");
  const possible = job.duplicates.filter((p) => p.merged === null && p.answer === null);

  return (
    <div className="stack" style={{ marginBottom: 16 }} data-testid="duplicates">
      {error ? <Notice kind="bad">{error}</Notice> : null}
      {into ? (
        <Notice kind="info">
          This is the same job as <Link href={`/jobs/${into.other.id}`}>{name(into)}</Link> ({into.reason.toLowerCase()}), so it was
          merged into that one and left your lists.{" "}
          <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => void answer(into, false)}>Not the same job</button>
        </Notice>
      ) : null}
      {also.length ? (
        <Notice kind="info">
          Also seen as{" "}
          {also.map((p, i) => (
            <Fragment key={p.id}>
              {i ? "; " : ""}
              <Link href={`/jobs/${p.other.id}`}>{name(p)}</Link> via {via(p)}{" "}
              <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => void answer(p, false)}>Not the same job</button>
            </Fragment>
          ))}
        </Notice>
      ) : null}
      {possible.map((p) => (
        <div key={p.id} className="todo" data-testid="possible-duplicate">
          <p>
            <strong>
              {p.kind === "agency" ? "Possibly the same role, posted by an agency: " : "Possible duplicate of "}
              <Link href={`/jobs/${p.other.id}`}>{name(p)}</Link>
            </strong>{" "}
            <span className="subtle">({p.reason.toLowerCase()})</span>
          </p>
          {p.other.status === "applied" ? (
            <p data-testid="may-have-applied">
              You may have applied to this role via {via(p)}
              {p.other.applied_on ? ` on ${shortDate(p.other.applied_on)}` : ""}.
              {job.lead === "recruiter_invite"
                ? " Check with the recruiter before agreeing to be put forward: two applications for one role can cost you the candidacy."
                : ""}
            </p>
          ) : null}
          <div className="row">
            <button className="btn btn-sm" onClick={() => setOpen(open === p.id ? null : p.id)}>
              {open === p.id ? "Hide the comparison" : "View the other job"}
            </button>
            <button className="btn btn-sm" disabled={busy} onClick={() => void answer(p, true)}>Same job</button>
            <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => void answer(p, false)}>Different job</button>
          </div>
          {open === p.id ? <CompareJobs job={job} pair={p} /> : null}
        </div>
      ))}
    </div>
  );
}

/**
 * Everything you have to do on this job, in amber, each with the button that fixes it. For Top matches it opens
 * with "Ready to apply?". Answers saved here go to the answer bank and count for every job.
 */
function TodoPanel(props: {
  job: UserJobDetail;
  onJob: (j: UserJobDetail) => void;
  onPaste: () => void;
  onStatus: (s: UserJobDetail["status"]) => void;
}) {
  const { job } = props;
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const active = job.status === "new" || job.status === "seen";
  const readiness = active ? job.readiness : null;
  if (!job.todos.length && !readiness) return null;

  async function run(t: Todo, fn: () => Promise<unknown>) {
    setBusy(t.key);
    setErrors((e) => ({ ...e, [t.key]: "" }));
    try {
      await fn();
      props.onJob(await api.job(job.id));
    } catch (e) {
      setErrors((x) => ({ ...x, [t.key]: errorMessage(e) }));
    } finally {
      setBusy(null);
    }
  }

  const resolve = (t: Todo) => run(t, () => api.resolveBlocker(job.id, t.key, t.kind === "question" ? drafts[t.key] ?? "" : undefined));

  return (
    <section className="card" id="todo" data-testid="todo-panel">
      <div className="card-head">
        <h2>{readiness ? "Ready to apply?" : "To do"}</h2>
        {readiness ? (
          <span className={`badge ${readiness.status === "ready" ? "badge-good" : "badge-warn"}`} data-testid="readiness-status">
            {readiness.status === "ready" ? "Ready" : `Needs your input (${readiness.blockers.length})`}
          </span>
        ) : null}
        {job.todos.length ? <span className="badge badge-warn" data-testid="todo-total">{job.todos.length} to do</span> : null}
      </div>
      {!job.todos.length ? (
        <p className="muted">Nothing is missing. Open the listing and apply; BrewMyJob never applies for you. Then mark it Applied.</p>
      ) : (
        <ul className="blockers">
          {job.todos.map((t) => (
            <li key={t.key} className="todo" data-testid="todo">
              <div><strong>{t.title}</strong></div>
              <div className="subtle">{t.detail}</div>
              {t.kind === "question" ? (
                <form className="row" onSubmit={(e) => { e.preventDefault(); void resolve(t); }}>
                  <input className="input grow" aria-label={`Answer: ${t.title}`} value={drafts[t.key] ?? ""}
                    onChange={(e) => setDrafts((d) => ({ ...d, [t.key]: e.target.value }))} placeholder="Your answer" />
                  <button className="btn btn-sm btn-primary" disabled={busy === t.key || !(drafts[t.key] ?? "").trim()}>Save answer</button>
                </form>
              ) : t.kind === "gap" ? (
                <div className="row">
                  <button className="btn btn-sm" disabled={busy === t.key} onClick={() => resolve(t)}>I&apos;ll address it</button>
                  <button className="btn btn-sm btn-ghost" disabled={busy === t.key} data-testid="not-a-fit"
                    title="Re-rate the job: it moves to Other jobs. You can undo this."
                    onClick={() => run(t, () => api.notAFit(job.id, t.key.replace("gap:", "") as Parameters<typeof api.notAFit>[1]))}>
                    Not a fit
                  </button>
                </div>
              ) : t.kind === "description" ? (
                <div><button className="btn btn-sm" onClick={props.onPaste}>Paste description</button></div>
              ) : t.kind === "cover_letter" ? (
                <div><Link className="btn btn-sm" href="/profile#cover-letters">Add a cover letter</Link></div>
              ) : t.kind === "expiry" ? (
                <div className="row">
                  <button className="btn btn-sm" disabled={busy === t.key} onClick={() => run(t, () => api.stillOpen(job.id))}>It&apos;s still open</button>
                  <button className="btn btn-sm btn-ghost" disabled={busy === t.key} onClick={() => props.onStatus("expired")}>Mark as expired</button>
                </div>
              ) : (
                <div><Link className="btn btn-sm" href={`/applications?open=${job.application?.id ?? ""}`}>Update the application</Link></div>
              )}
              {errors[t.key] ? <span className="field-error">{errors[t.key]}</span> : null}
            </li>
          ))}
        </ul>
      )}
      {readiness ? (
        <p className="subtle" style={{ marginTop: 8 }}>Answers you save here are kept in your <Link href="/profile?tab=answers">answer bank</Link> and reused on every job.</p>
      ) : null}
    </section>
  );
}

/** Where the points between the score and 100 went. */
function WhyNot100({ match }: { match: MatchDetail }) {
  if (match.score >= 100) return null;
  return (
    <div data-testid="why-not-100">
      <h3 style={{ marginTop: 16 }}>Why not 100%</h3>
      {!match.explained ? (
        <p className="muted">This job was scored before the breakdown existed. It appears after the next re-score (for example when you change your profile).</p>
      ) : (
        <ul className="ranking" data-testid="points-lost">
          {match.points_lost.map((p) => (
            <li key={p.key}>
              <span className="grow">{p.label}</span>
              <span className="num lost">−{p.points}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

type ReqMark = { mark: string; label: string; cls: string };
const UNCLEAR: ReqMark = { mark: "?", label: "Judge this one yourself", cls: "muted" };
const REQ_MARK: Record<string, ReqMark> = {
  met: { mark: "✓", label: "Shown in your resume", cls: "good" },
  partly: { mark: "◐", label: "Partly shown", cls: "warn" },
  missing: { mark: "✗", label: "Not shown in your resume", cls: "bad" },
  unclear: { mark: "?", label: "Judge this one yourself", cls: "muted" },
};

/** The description's requirements by section (user feedback 2026-11-16): must-haves are scored, preferred items
 *  are shown only. */
function RequirementsCheck({ match }: { match: MatchDetail }) {
  const must = match.must_haves ?? [];
  const preferred = match.preferred ?? [];
  if (!must.length && !preferred.length) return null;
  const short = must.filter((r) => r.status === "missing").length;
  const list = (items: typeof must, testId: string) => (
    <ul className="req-list" data-testid={testId}>
      {items.map((r) => {
        const m = REQ_MARK[r.status] ?? UNCLEAR;
        const gaps = r.missing ?? [];
        return (
          <li key={r.text} className={`req ${m.cls}`}>
            <span className="req-mark" title={m.label} aria-label={m.label}>{m.mark}</span>
            <span>
              {r.text}
              {gaps.length && r.status !== "missing" ? <span className="subtle"> · not shown: {gaps.join(", ")}</span> : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
  return (
    <div className={`skills-check${short ? " has-gaps" : ""}`} data-testid="requirements-check">
      <h3>Requirements</h3>
      {must.length ? (
        <div>
          <div className="label">Must-haves in the description{short ? ` (${short} not shown in your resume)` : ""}</div>
          {list(must, "must-haves")}
        </div>
      ) : null}
      {preferred.length ? (
        <div>
          <div className="label">Preferred only (not scored)</div>
          {list(preferred, "preferred")}
        </div>
      ) : null}
    </div>
  );
}

/** The skills check, highlighted: what the job asks for that your resume doesn't show, your key skills it asks
 *  for, and what you have. */
function SkillsCheck({ jobId, match, onJob }: { jobId: string; match: MatchDetail; onJob: (j: UserJobDetail) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!match.explained) return null;
  const keySkills = match.key_skills_found ?? [];
  const nothing = !match.skills_missing.length && !match.skills_have.length && !keySkills.length;

  async function have(skill: string) {
    setBusy(skill);
    setError(null);
    try {
      onJob(await api.addSkill(jobId, skill));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={`skills-check${match.skills_missing.length ? " has-gaps" : ""}`} data-testid="skills-check">
      <h3>Skills</h3>
      {nothing ? (
        <p className="subtle">The job doesn&apos;t name any skills yet. Paste the full description below to check them.</p>
      ) : null}
      {match.skills_missing.length ? (
        <div>
          <div className="label">Asked for in the job, not shown in your resume ({match.skills_missing.length})</div>
          <ul className="skill-list" data-testid="skills-missing">
            {match.skills_missing.map((s) => (
              <li key={s}>
                <span className="chip plain bad">{s}</span>
                <button className="btn btn-sm btn-ghost" disabled={busy !== null} onClick={() => have(s)}
                  title={`Adds it to the Skill Match profile of “${match.best_resume_label ?? "your resume"}”. Only for skills you really have: add it to the resume too, so tailored resumes can claim it.`}>
                  {busy === s ? "Adding…" : "Add to match profile"}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {keySkills.length ? (
        <div>
          <div className="label">Your key skills this job asks for</div>
          <div className="row" style={{ gap: 6 }} data-testid="key-skills-found">
            {keySkills.map((s) => <span key={s} className="chip plain good">{s}</span>)}
          </div>
        </div>
      ) : null}
      {match.skills_have.length ? (
        <div>
          <div className="label">Asked for and shown in your resume</div>
          <div className="row" style={{ gap: 6 }} data-testid="skills-have">
            {match.skills_have.map((s) => <span key={s} className="chip plain good">{s}</span>)}
          </div>
        </div>
      ) : null}
      {error ? <span className="field-error">{error}</span> : null}
    </div>
  );
}

/** Another resume side by side with the suggested one: score, each factor, and the skills only one of them shows. */
function ResumeCompare({ jobId, match, resumeId, onDownload }: {
  jobId: string; match: MatchDetail; resumeId: string; onDownload: (id: string, label: string) => void;
}) {
  const [other, setOther] = useState<ResumeComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setOther(null);
    setError(null);
    api.compareResume(jobId, resumeId).then(setOther).catch((e) => setError(errorMessage(e)));
  }, [jobId, resumeId]);
  const best = match.ranking[0];
  if (error) return <Notice kind="bad">{error}</Notice>;
  if (!other || !best) return <div className="loading">Comparing…</div>;

  const mine = Object.fromEntries(match.factors.map((f) => [f.key, f.score]));
  const theirs = Object.fromEntries(other.factors.map((f) => [f.key, f.score]));
  const keys = [...match.factors.map((f) => f.key), ...other.factors.map((f) => f.key).filter((k) => !(k in mine))];
  const label = (k: string) => (match.factors.find((f) => f.key === k) ?? other.factors.find((f) => f.key === k))?.label ?? k;
  const onlyOther = other.skills_have.filter((s) => !match.skills_have.includes(s));
  const onlyBest = match.skills_have.filter((s) => !other.skills_have.includes(s));
  const cell = (a: number | undefined, b: number | undefined) =>
    a === undefined ? "subtle" : b !== undefined && a > b ? "num better" : b !== undefined && a < b ? "num worse" : "num";

  return (
    <div className="compare" data-testid="resume-compare">
      <table className="compare-table">
        <thead>
          <tr><th></th><th>{best.label} <span className="subtle">(suggested)</span></th><th>{other.label}</th></tr>
        </thead>
        <tbody>
          <tr className="total">
            <td>Match</td>
            <td className={cell(match.score, other.score)}>{match.score}%</td>
            <td className={cell(other.score, match.score)} data-testid="compare-score">{other.score}%</td>
          </tr>
          {keys.map((k) => (
            <tr key={k}>
              <td>{label(k)}</td>
              <td className={cell(mine[k], theirs[k])}>{mine[k] ?? "–"}</td>
              <td className={cell(theirs[k], mine[k])}>{theirs[k] ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted" style={{ marginTop: 8 }}>{other.reason}</p>
      {onlyOther.length || onlyBest.length ? (
        <div className="grid-2" style={{ marginTop: 8 }}>
          <div>
            <div className="label">Only {other.label} shows</div>
            <div className="row" style={{ gap: 6 }}>{onlyOther.length ? onlyOther.map((s) => <span key={s} className="chip plain good">{s}</span>) : <span className="subtle">Nothing extra</span>}</div>
          </div>
          <div>
            <div className="label">Only {best.label} shows</div>
            <div className="row" style={{ gap: 6 }}>{onlyBest.length ? onlyBest.map((s) => <span key={s} className="chip plain">{s}</span>) : <span className="subtle">Nothing extra</span>}</div>
          </div>
        </div>
      ) : null}
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn btn-sm" onClick={() => onDownload(other.resume_id, other.label)}>Download {other.label}</button>
        <span className="subtle">You can apply with either; the suggestion is just the higher score.</span>
      </div>
    </div>
  );
}

/** The match: score, suggested resume and cover letter, every resume's %, and the factors behind it. */
/** Shown while the job is re-scored after a new description (user feedback 2026-11-11: make it noticeable). */
function Rescoring() {
  return (
    <div className="rescoring" role="status" data-testid="rescoring">
      <span className="rescoring-spin" aria-hidden="true" />
      Updating the match with the new description… the score changes here in a few seconds.
    </div>
  );
}

function MatchPanel({ jobId, match, rescoring, onJob }: { jobId: string; match: MatchDetail | null; rescoring: boolean; onJob: (j: UserJobDetail) => void }) {
  const [letter, setLetter] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [compareId, setCompareId] = useState<string | null>(null);

  if (!match) {
    return (
      <section className={`card${rescoring ? " is-rescoring" : ""}`} data-testid="match-panel">
        <div className="card-head"><h2>Match</h2></div>
        {rescoring ? <Rescoring /> : (
          <p className="muted">Not scored yet. Scores appear once you <Link href="/profile">add a resume</Link>.</p>
        )}
      </section>
    );
  }
  const band = BAND[match.band];
  const best = match.ranking[0];

  async function download(id: string, label: string) {
    try {
      downloadBlob(await api.resumeFile(id), label);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <section className={`card${rescoring ? " is-rescoring" : ""}`} data-testid="match-panel">
      <div className="card-head">
        <h2>Match</h2>
        <span className={`badge badge-${band.kind}`}>{band.label}</span>
      </div>
      {rescoring ? <Rescoring /> : null}
      {error ? <Notice kind="bad">{error}</Notice> : null}
      <div className="match-head">
        <div className={`score score-lg score-${band.kind}`} data-testid="match-score">{match.score}%</div>
        <div className="stack-tight">
          {match.primary_score !== null ? <div>Your primary resume: <strong data-testid="primary-score">{match.primary_score}%</strong></div> : null}
          {match.filter_reason ? <div>Ruled out: {match.filter_reason}</div> : null}
          {match.search_profile_name ? <div className="subtle">Judged against your “{match.search_profile_name}” Skill Match profile</div> : null}
          {match.provisional ? (
            <div className="subtle">Scored from the alert&apos;s few facts. Paste the full description below for a sharper score.</div>
          ) : null}
        </div>
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        <div className="suggest" data-testid="suggested-resume">
          <div className="subtle">Suggested resume</div>
          {best ? (
            <>
              <div className="row"><strong>{best.label}</strong><span className="badge">{best.score}%</span>{best.is_primary ? <span className="badge badge-info">Primary</span> : null}</div>
              <div className="muted">{best.reason}</div>
              <div><button className="btn btn-sm" onClick={() => download(best.resume_id, best.label)}>Download</button></div>
            </>
          ) : <div className="muted">No resume yet.</div>}
        </div>
        <div className="suggest" data-testid="suggested-cover-letter">
          <div className="subtle">Suggested cover letter</div>
          {match.cover_letter_id ? (
            <>
              <strong>{match.cover_letter_label}</strong>
              <details onToggle={async (e) => {
                if ((e.target as HTMLDetailsElement).open && letter === null && match.cover_letter_id) {
                  try { setLetter((await api.coverLetter(match.cover_letter_id)).text); } catch (err) { setError(errorMessage(err)); }
                }
              }}>
                <summary>Show</summary>
                <div className="description">{letter ?? "Loading…"}</div>
              </details>
            </>
          ) : (
            <div className="muted">No cover letters yet. <Link href="/profile">Add one</Link> to get a suggestion.</div>
          )}
        </div>
      </div>
      <p className="subtle" style={{ marginTop: 8 }}>A resume and cover letter tailored to this job arrive with the Anthropic key. You always apply yourself.</p>

      {match.ranking.length > 1 ? (
        <>
          <h3 style={{ marginTop: 16 }}>All your resumes</h3>
          <ul className="ranking" data-testid="resume-ranking">
            {match.ranking.map((r, i) => (
              <li key={r.resume_id}>
                <span className="grow">{r.label}{r.is_primary ? <span className="badge badge-info" style={{ marginLeft: 6 }}>Primary</span> : null}</span>
                <Bar value={r.score} />
                <span className="num">{r.score}%</span>
                {i === 0 ? (
                  <span className="subtle" style={{ minWidth: 76, textAlign: "right" }}>Suggested</span>
                ) : (
                  <button className="btn btn-sm btn-ghost" style={{ minWidth: 76 }} aria-pressed={compareId === r.resume_id}
                    aria-label={`Compare ${r.label} with the suggested resume`}
                    onClick={() => setCompareId(compareId === r.resume_id ? null : r.resume_id)}>
                    {compareId === r.resume_id ? "Close" : "Compare"}
                  </button>
                )}
              </li>
            ))}
          </ul>
          {compareId ? (
            <ResumeCompare jobId={jobId} match={match} resumeId={compareId} onDownload={download} />
          ) : null}
        </>
      ) : null}

      <RequirementsCheck match={match} />
      <SkillsCheck jobId={jobId} match={match} onJob={onJob} />
      <WhyNot100 match={match} />

      <h3 style={{ marginTop: 16 }}>Each factor</h3>
      <ul className="ranking">
        {match.factors.map((f) => (
          <li key={f.key}><span className="grow">{f.label}</span><Bar value={f.score} /><span className="num">{f.score}</span></li>
        ))}
      </ul>
      {match.strengths.length || match.gaps.length ? (
        <div className="row" style={{ marginTop: 10 }}>
          {match.strengths.map((s) => <span key={s} className="chip plain good">{s}</span>)}
          {match.gaps.map((s) => <span key={s} className="chip plain bad">Gap: {s}</span>)}
        </div>
      ) : null}
    </section>
  );
}

/** Your LinkedIn connections at this job's company (milestone 7): a warm path to the team. */
function PeopleYouKnow({ jobId }: { jobId: string }) {
  const [people, setPeople] = useState<JobPeople | null>(null);
  useEffect(() => {
    api.jobPeople(jobId).then(setPeople).catch(() => setPeople(null));
  }, [jobId]);
  if (!people) return null;
  if (!people.imported) {
    return <p className="subtle" style={{ marginTop: 14 }}>Import your LinkedIn connections on <Link href="/networking">Networking</Link> to see who you know here.</p>;
  }
  if (!people.items.length) return null;
  return (
    <div className="stack" style={{ marginTop: 14, gap: 6 }} data-testid="people-you-know">
      <h3>People you know at {people.company}</h3>
      <ul className="doc-list">
        {people.items.map((p) => (
          <li key={p.id}>
            <div className="grow stack-tight"><strong>{p.name}</strong><span className="subtle">{[p.position, p.company].filter(Boolean).join(" · ")}</span></div>
            {p.profile_url ? <a className="btn btn-sm" href={p.profile_url} target="_blank" rel="noopener noreferrer">Profile ↗</a> : null}
          </li>
        ))}
      </ul>
      <p className="subtle">Ask one of them about the team or a referral. <Link href="/networking">Today&apos;s list</Link> drafts the note.</p>
    </div>
  );
}

/** Who to contact, at the top of the job: saved contacts, the recruiter the email named, emails and LinkedIn
 *  profiles written in the description, and people you know there. Shown only when there's someone. */
function WhoToContact({ jobId }: { jobId: string }) {
  const [list, setList] = useState<ContactList | null>(null);
  const [people, setPeople] = useState<JobPeople | null>(null);
  useEffect(() => {
    api.contacts(jobId).then(setList).catch(() => setList(null));
    api.jobPeople(jobId).then(setPeople).catch(() => setPeople(null));
  }, [jobId]);
  const saved = list?.items ?? [];
  const found = list?.found ?? [];
  const known = people?.items ?? [];
  if (!saved.length && !found.length && !list?.from_email && !known.length) return null;

  return (
    <section className="card highlight" style={{ marginBottom: 16 }} data-testid="who-to-contact">
      <div className="card-head">
        <h2>Who to contact</h2>
        <span className="subtle">BrewMyJob never messages anyone; these open your own email or LinkedIn</span>
      </div>
      <ul className="doc-list">
        {list?.from_email ? (
          <li><div className="grow"><strong>{list.from_email}</strong> <span className="subtle">· recruiter who sent this job</span></div></li>
        ) : null}
        {saved.map((c) => (
          <li key={c.id}>
            <div className="grow stack-tight">
              <strong>{c.name ?? c.email ?? "Contact"}{c.role ? <span className="subtle"> · {c.role}</span> : null}</strong>
              <span className="subtle">Saved by you</span>
            </div>
            {c.email ? <a className="btn btn-sm" href={`mailto:${c.email}`}>✉ {c.email}</a> : null}
            {c.linkedin_url ? <a className="btn btn-sm" href={c.linkedin_url} target="_blank" rel="noopener noreferrer">LinkedIn profile ↗</a> : null}
          </li>
        ))}
        {found.map((f) => (
          <li key={f.url} data-testid="found-contact">
            <div className="grow stack-tight">
              <strong>{f.kind === "email" ? f.value : `LinkedIn: ${f.value}`}</strong>
              <span className="subtle">In the job description{f.context ? `: “${f.context}”` : ""}</span>
            </div>
            {f.kind === "email"
              ? <a className="btn btn-sm btn-primary" href={f.url}>✉ Email</a>
              : <a className="btn btn-sm btn-primary" href={f.url} target="_blank" rel="noopener noreferrer">LinkedIn profile ↗</a>}
          </li>
        ))}
        {known.slice(0, 3).map((p) => (
          <li key={p.id}>
            <div className="grow stack-tight">
              <strong>{p.name}</strong>
              <span className="subtle">You know them · {[p.position, p.company].filter(Boolean).join(" · ")}</span>
            </div>
            {p.profile_url ? <a className="btn btn-sm" href={p.profile_url} target="_blank" rel="noopener noreferrer">LinkedIn profile ↗</a> : null}
          </li>
        ))}
      </ul>
      {known.length > 3 ? <p className="subtle">{known.length - 3} more people you know there, under Where it came from.</p> : null}
    </section>
  );
}

const NO_CONTACT: ContactIn = { name: "", role: "", linkedin_url: "", email: "", note: "" };

/** People for this job: the recruiter the email named, and anyone you saved. BrewMyJob never contacts them. */
function Contacts({ jobId }: { jobId: string }) {
  const [list, setList] = useState<ContactList | null>(null);
  const [form, setForm] = useState<ContactIn | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.contacts(jobId).then(setList).catch((e) => setError(errorMessage(e)));
  }, [jobId]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setBusy(true);
    setErrors({});
    setError(null);
    try {
      const body: ContactIn = {
        name: toStrOrNull(form.name ?? ""),
        role: toStrOrNull(form.role ?? ""),
        linkedin_url: toStrOrNull(form.linkedin_url ?? ""),
        email: toStrOrNull(form.email ?? ""),
        note: toStrOrNull(form.note ?? ""),
      };
      setList(await api.addContact(jobId, body));
      setForm(null);
    } catch (err) {
      const f = fieldErrors(err);
      setErrors(f);
      // "Add a name, a LinkedIn profile link or an email" is about the whole form, not one field.
      if (f[""]) setError(f[""].replace(/^Value error, /, ""));
      else if (!Object.keys(f).length) setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    try {
      await api.deleteContact(jobId, id);
      setList((l) => (l ? { ...l, items: l.items.filter((c) => c.id !== id) } : l));
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const set = (k: keyof ContactIn) => (e: { target: { value: string } }) => {
    const v = e.target.value;
    setForm((f) => (f ? { ...f, [k]: v } : f));
  };

  return (
    <div className="stack" style={{ marginTop: 14, gap: 8 }} data-testid="contacts">
      <div className="row">
        <h3>People for this job</h3>
        <span className="spacer" />
        {!form ? <button className="btn btn-sm" onClick={() => setForm(NO_CONTACT)}>Add a contact</button> : null}
      </div>
      {list?.from_email ? <div className="muted">The email named the recruiter: <strong>{list.from_email}</strong></div> : null}
      {list && !list.items.length && !list.from_email && !form ? (
        <p className="subtle">
          Alert emails rarely say who posted a job. If the listing shows the hiring team or a recruiter, save them here. BrewMyJob only keeps the
          details for you; it never messages anyone.
        </p>
      ) : null}
      {list?.items.length ? (
        <ul className="doc-list">
          {list.items.map((c) => (
            <li key={c.id} data-testid="contact">
              <div className="grow stack-tight">
                <strong>{c.name ?? c.email ?? "Contact"}{c.role ? <span className="subtle"> · {c.role}</span> : null}</strong>
                <span className="row subtle">
                  {c.linkedin_url ? <a href={c.linkedin_url} target="_blank" rel="noopener noreferrer">LinkedIn profile ↗</a> : null}
                  {c.email ? <a href={`mailto:${c.email}`}>{c.email}</a> : null}
                </span>
                {c.note ? <span className="subtle">{c.note}</span> : null}
              </div>
              <button className="btn btn-sm btn-ghost danger" aria-label={`Remove ${c.name ?? c.email ?? "contact"}`} onClick={() => remove(c.id)}>Remove</button>
            </li>
          ))}
        </ul>
      ) : null}
      {form ? (
        <form className="stack" onSubmit={save} noValidate>
          <div className="grid-2">
            <Field label="Name" htmlFor="c-name" error={errors.name}><input id="c-name" className="input" value={form.name ?? ""} onChange={set("name")} /></Field>
            <Field label="Role" htmlFor="c-role" error={errors.role} hint="e.g. Recruiter, Hiring manager">
              <input id="c-role" className="input" value={form.role ?? ""} onChange={set("role")} />
            </Field>
            <Field label="LinkedIn profile" htmlFor="c-li" error={errors.linkedin_url}>
              <input id="c-li" className="input" placeholder="linkedin.com/in/…" value={form.linkedin_url ?? ""} onChange={set("linkedin_url")} />
            </Field>
            <Field label="Email" htmlFor="c-email" error={errors.email}><input id="c-email" className="input" type="email" value={form.email ?? ""} onChange={set("email")} /></Field>
            <Field label="Note" htmlFor="c-note" error={errors.note} className="span-all"><input id="c-note" className="input" value={form.note ?? ""} onChange={set("note")} /></Field>
          </div>
          {error ? <Notice kind="bad">{error}</Notice> : null}
          <div className="row">
            <button className="btn btn-primary btn-sm" disabled={busy}>{busy ? "Saving…" : "Save contact"}</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setForm(null); setErrors({}); setError(null); }}>Cancel</button>
          </div>
        </form>
      ) : error ? <Notice kind="bad">{error}</Notice> : null}
    </div>
  );
}

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<UserJobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pasting, setPasting] = useState(false);
  const [text, setText] = useState("");
  const [textError, setTextError] = useState<string | undefined>();
  const [rescoring, setRescoring] = useState(false);
  const [rescoreLate, setRescoreLate] = useState(false);

  // After a pasted description the job is re-scored in the background: check back until the score changes.
  useEffect(() => {
    if (!rescoring || !job) return;
    const before = job.match?.scored_at;
    let tries = 0;
    const t = setInterval(async () => {
      tries += 1;
      const fresh = await api.job(job.id).catch(() => null);
      if (fresh && fresh.match?.scored_at !== before) {
        setJob(fresh);
        setRescoring(false);
      } else if (tries >= 15) {
        setRescoring(false);
        setRescoreLate(true); // said, not dropped silently (2026-11-12); a sweep rescores it within 15 minutes
      }
    }, 2000);
    return () => clearInterval(t);
  }, [rescoring, job]);

  useEffect(() => {
    let live = true;
    api
      .job(id)
      .then(async (j) => {
        if (!live) return;
        setJob(j);
        // Opening a new job marks it seen. Not worth an error if another tab got there first.
        if (j.status === "new") {
          const seen = await api.setJobStatus(j.id, "seen", j.version).catch(() => null);
          if (live && seen) setJob(seen);
        }
      })
      .catch((e) => live && setError(errorMessage(e)));
    return () => {
      live = false;
    };
  }, [id]);

  const [notForMe, setNotForMe] = useState(false);

  async function setStatus(status: UserJobDetail["status"]) {
    if (!job) return;
    setBusy(true);
    setError(null);
    try {
      setJob(await api.setJobStatus(job.id, status, job.version));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function undoNotAFit() {
    if (!job) return;
    setBusy(true);
    setError(null);
    try {
      setJob(await api.undoNotAFit(job.id));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveDescription(e: FormEvent) {
    e.preventDefault();
    if (!job) return;
    setBusy(true);
    setTextError(undefined);
    try {
      setJob(await api.pasteDescription(job.id, text, job.version));
      setPasting(false);
      setText("");
      setRescoring(true);
      setRescoreLate(false);
      // Back to the top, where the new score and the rescoring notice show (user feedback 2026-11-11).
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setTextError(fieldErrors(err).text ?? errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (error && !job) return <Notice kind="bad">{error}</Notice>;
  if (!job) return <div className="loading">Loading…</div>;
  const j = job.job;
  const details = Object.entries(j.details ?? {}).filter(([k, v]) => k !== "recruiter" && (typeof v === "string" || typeof v === "number"));
  const active = job.status === "new" || job.status === "seen";
  const app = job.application;
  const applyTo = applyLink(j.sources, j.company, job.apply_url);
  // The listing's own skills; when it names none, the ones the scorer found in the description (not the user's
  // key skills, which are the user's wording).
  const mine = job.match?.key_skills_found ?? [];
  const asked = j.skills.length
    ? j.skills
    : [...(job.match?.skills_missing ?? []), ...(job.match?.skills_have ?? [])].filter((s) => !mine.includes(s));

  return (
    <>
      <p className="subtle" style={{ marginBottom: 8 }}><Link href="/jobs">← Jobs</Link></p>
      <PageHeader
        title={j.title}
        sub={
          <>
            {j.company ?? "Company not named"}
            {factsLine(j) ? ` · ${factsLine(j)}` : ""}
            <span data-testid="job-source"> · via {sourceLabels(j.sources, j.company).join(", ")}</span>
          </>
        }
        actions={
          active ? (
            <>
              {applyTo ? (
                <a className="btn btn-primary" href={applyTo.href} target="_blank" rel="noopener noreferrer" data-testid="apply-link">
                  {applyTo.label} ↗
                </a>
              ) : null}
              <button className={applyTo ? "btn" : "btn btn-primary"} disabled={busy} onClick={() => setStatus("applied")} title="You applied on the portal: track it here">
                Mark as applied
              </button>
              <button className="btn btn-ghost" disabled={busy} onClick={() => setNotForMe(true)} title="Ignore it and say why, so similar jobs score lower">Not for me</button>
              <button className="btn btn-ghost" disabled={busy} onClick={() => setStatus("ignored")}>Ignore</button>
              <button className="btn btn-ghost" disabled={busy} onClick={() => setStatus("expired")} title="The posting has closed">Expired</button>
            </>
          ) : job.status === "applied" ? (
            <>
              <Link className="btn btn-primary" href={`/applications?open=${app?.id ?? ""}`}>Track application</Link>
              <button className="btn btn-ghost" disabled={busy} onClick={() => setStatus("seen")} title="Marked by mistake">Undo applied</button>
            </>
          ) : job.status === "review" ? (
            // Added from Google, waiting for review (2026-11-17): apply straight away, or keep it or ignore it.
            <>
              {applyTo ? (
                <a className="btn btn-primary" href={applyTo.href} target="_blank" rel="noopener noreferrer" data-testid="apply-link">
                  {applyTo.label} ↗
                </a>
              ) : null}
              <button className={applyTo ? "btn" : "btn btn-primary"} disabled={busy} onClick={() => setStatus("seen")}
                title="Move it to your jobs: Top matches or Other jobs by its score">Keep</button>
              <button className="btn btn-ghost" disabled={busy} onClick={() => setStatus("applied")} title="You applied on the portal: track it here">
                Mark as applied
              </button>
              <button className="btn btn-ghost" disabled={busy} onClick={() => setStatus("ignored")}>Ignore</button>
            </>
          ) : job.status === "duplicate" ? null : (
            <button className="btn" disabled={busy} onClick={() => setStatus("seen")}>Restore</button>
          )
        }
      />
      {error ? <div style={{ marginBottom: 16 }}><Notice kind="bad">{error}</Notice></div> : null}
      {unverifiedNote(job.job) ? (
        <div style={{ marginBottom: 16 }} data-testid="unverified-notice"><Notice kind="warn"><strong>Unverified.</strong> {unverifiedNote(job.job)}</Notice></div>
      ) : null}
      {notForMe && active ? <NotForMe job={job} onJob={setJob} onClose={() => setNotForMe(false)} /> : null}
      {job.learned ? (
        <div style={{ marginBottom: 16 }} data-testid="learned-notice">
          <Notice kind="warn">
            You said jobs like this aren&apos;t for you (<strong>{job.learned}</strong>), so it scores at most 40 and sits in Other jobs.{" "}
            <Link href="/profile#learned">Change on Profile</Link>
          </Notice>
        </div>
      ) : null}
      <Duplicates job={job} onJob={setJob} />
      <WhoToContact jobId={job.id} />
      {job.not_a_fit.length ? (
        <div style={{ marginBottom: 16 }} data-testid="not-a-fit-notice">
          <Notice kind="warn">
            You marked this job not a fit ({job.not_a_fit.map((g) => job.match?.factors.find((f) => f.key === g)?.label ?? g).join(", ")}), so it scores at most 40
            and sits in Other jobs.{" "}
            <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => void undoNotAFit()}>Undo</button>
          </Notice>
        </div>
      ) : null}
      {job.status === "ignored" ? (
        <div style={{ marginBottom: 16 }} data-testid="ignored-notice">
          <Notice kind="warn">
            {reasonLabel(job.not_for_me) ? `Not for you: ${reasonLabel(job.not_for_me)}. ` : "You ignored this job. "}
            It stays in the Ignored tab unless you restore it.
          </Notice>
        </div>
      ) : null}
      {job.status === "expired" ? (
        <div style={{ marginBottom: 16 }}>
          <Notice kind="warn">
            {job.expired_by === "auto"
              ? "No alert has shown this job for a while, so it moved to Expired. If it's still open, restore it."
              : "You marked this job as expired. Restore it if it reopens."}
          </Notice>
        </div>
      ) : null}
      {app ? (
        <div style={{ marginBottom: 16 }}>
          <Notice kind="info">
            {APPLICATION_STATUS[app.status]?.label ?? app.status} · applied on{" "}
            {new Date(app.applied_on).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
            {app.follow_up_on ? ` · follow up on ${new Date(app.follow_up_on).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}` : ""}
          </Notice>
        </div>
      ) : null}

      <TodoPanel job={job} onJob={setJob} onStatus={setStatus}
        onPaste={() => { setPasting(true); document.getElementById("description")?.scrollIntoView({ behavior: "smooth" }); }} />
      {rescoreLate ? (
        <Notice kind="warn">
          The new score is taking longer than usual. It updates on its own within 15 minutes; reload this page to see it.
        </Notice>
      ) : null}
      <MatchPanel jobId={job.id} match={job.match} rescoring={rescoring} onJob={setJob} />

      <section className="card">
        <div className="card-head"><h2>Where it came from</h2><span className="subtle">First seen {seenAgo(job.first_seen_at).toLowerCase()}</span></div>
        <dl className="kv">
          <dt>Kind</dt>
          <dd>{LEAD_LABEL[job.lead]}{job.outside_preference ? " · outside your portal preferences" : ""}</dd>
          <dt>Listings</dt>
          <dd className="row">
            {j.sources.map((s) =>
              s.url ? (
                <a key={s.source} className="btn btn-sm" href={s.url} target="_blank" rel="noopener noreferrer">
                  Open on {sourceLabel(s.source, j.company)} ↗
                </a>
              ) : (
                <span key={s.source} className="badge">{sourceLabel(s.source, j.company)} (no public page)</span>
              ),
            )}
          </dd>
          {job.card_lines.length ? (<><dt>About you</dt><dd>{job.card_lines.join(" · ")}</dd></>) : null}
          {asked.length ? (
            <><dt>{j.skills.length ? "Skills" : "Skills in the description"}</dt>
              <dd className="row" data-testid="job-skills">{asked.map((s) => <span key={s} className="chip plain">{s}</span>)}</dd></>
          ) : null}
          {details.map(([k, v]) => (<Fragment key={k}><dt>{k}</dt><dd>{String(v)}</dd></Fragment>))}
        </dl>
        {job.apply_url && isNaukriSignInLink(job.apply_url) ? (
          <div className="stack" style={{ marginTop: 14 }}>
            <Notice kind="warn">
              This recruiter&apos;s apply link signs you in to Naukri. Open it yourself; don&apos;t share it. BrewMyJob never opens it.
            </Notice>
            <div><a className="btn btn-primary btn-sm" href={job.apply_url} target="_blank" rel="noopener noreferrer">Apply on Naukri ↗</a></div>
          </div>
        ) : null}
        <PeopleYouKnow jobId={job.id} />
        <Contacts jobId={job.id} />
      </section>

      {job.status !== "duplicate" ? <ApplyKit jobId={job.id} /> : null}

      <section className="card" id="description">
        <div className="card-head">
          <h2>Description</h2>
          {j.description_source === "you" ? <span className="subtle">Pasted by you · visible only to you</span> : null}
          {j.description && !pasting ? <button className="btn btn-sm btn-ghost" onClick={() => { setText(j.description ?? ""); setPasting(true); }}>Replace</button> : null}
          {/* Save on the top right, next to the heading (user, 2026-11-17): a long paste pushes the bottom out of view. */}
          {pasting ? (
            <span className="row" style={{ marginLeft: "auto" }}>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setPasting(false); setTextError(undefined); }}>Cancel</button>
              <button type="submit" form="description-form" className="btn btn-primary btn-sm" disabled={busy}>{busy ? "Saving…" : "Save description"}</button>
            </span>
          ) : null}
        </div>
        {j.description && !pasting ? (
          <div className="description" data-testid="job-description">{j.description}</div>
        ) : null}
        {!j.description && !pasting ? (
          <div className="stack todo">
            <p>
              The alert email didn&apos;t include the full description. Open the listing, copy the description and paste it here: the
              job is then scored on the whole description, not just its title.
            </p>
            <div><button className="btn btn-sm" onClick={() => setPasting(true)}>Paste description</button></div>
          </div>
        ) : null}
        {pasting ? (
          <form id="description-form" className="stack" onSubmit={saveDescription} noValidate>
            <Field label="Full job description" htmlFor="desc" error={textError} hint="Stored for you only; it doesn't change what other users see.">
              <textarea id="desc" className="textarea" rows={12} value={text} onChange={(e) => setText(e.target.value)} />
            </Field>
          </form>
        ) : null}
        {j.about_company ? (<><h3 style={{ marginTop: 16 }}>About the company</h3><div className="description">{j.about_company}</div></>) : null}
        {j.offer ? (<><h3 style={{ marginTop: 16 }}>What they offer</h3><div className="description">{j.offer}</div></>) : null}
      </section>
    </>
  );
}
