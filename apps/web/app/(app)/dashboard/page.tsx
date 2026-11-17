"use client";
import type { Application, ApplicationList, Candidate, JobStats, Mail, SearchProfile, UserJob } from "@fitfirst/api";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { Icon } from "@/components/Icon";
import { errorMessage, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { APPLICATION_STATUS, BAND, seenAgo, sourceLabels } from "@/lib/jobs";
import { splitPlaces } from "@/lib/places";
import { useSession } from "@/lib/session";

/** The dashboard in the "command center" layout (2026-11-13): what needs you, the numbers, the best jobs, the
 *  pipeline, and who you know. Every number is the user's own; nothing here is sample data. */
type Data = {
  cand: Candidate;
  profiles: SearchProfile[];
  stats: JobStats;
  mail: Mail;
  due: ApplicationList;
  recent: ApplicationList;
  top: UserJob[];
};

const OPEN = ["applied", "interviewing", "offer"] as const;

/** Asked once of accounts made before sign-up asked it (2026-11-14): where to look for jobs. */
function JobLocationsAsk({ onSaved }: { onSaved: (c: Candidate) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSaved(await api.saveJobLocations(splitPlaces(text)));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card" data-testid="job-locations-ask">
      <div className="card-head"><h2>Where do you want to work?</h2></div>
      <p className="hint">Cities, or Remote, separated by commas. BrewMyJob looks for jobs there; you can change it on your Profile.</p>
      <form className="row" onSubmit={save} style={{ marginTop: 8 }}>
        <input className="input" aria-label="Where you want to work" placeholder="Bengaluru, Remote" value={text}
          onChange={(e) => setText(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
        <button className="btn btn-primary" disabled={busy || !splitPlaces(text).length}>{busy ? "Saving…" : "Save"}</button>
      </form>
      {error ? <Notice kind="bad">{error}</Notice> : null}
    </section>
  );
}

export default function Dashboard() {
  const { me } = useSession();
  const router = useRouter();
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [q, setQ] = useState("");

  useEffect(() => {
    Promise.all([
      api.candidate(),
      api.profiles(),
      api.jobStats(),
      api.mail(),
      api.applications({ due: true, limit: 5 }),
      api.applications({ limit: 6 }),
      api.jobs({ tab: "top", status: "active", limit: 5 }),
    ])
      .then(([cand, profiles, stats, mail, due, recent, top]) =>
        setData({ cand, profiles, stats, mail, due, recent, top: top.items }),
      )
      .catch((e) => setError(errorMessage(e)));
  }, []);

  if (error) return <Notice kind="bad">{error}</Notice>;
  if (!me || !data) return <div className="loading">Loading…</div>;
  const { cand, profiles, stats, mail, due, recent, top } = data;

  const steps = {
    profile: cand.completeness >= 70,
    search: profiles.some((p) => p.active),
    mail: mail.receiving,
  };
  const setupDone = steps.profile && steps.search && steps.mail;
  const openApps = OPEN.reduce((n, k) => n + (recent.counts[k] ?? 0), 0);
  const scored = Math.max(0, stats.active - stats.unscored);
  const copy = async () => {
    await navigator.clipboard.writeText(me.forwarding_address);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const search = (e: FormEvent) => {
    e.preventDefault();
    const params = new URLSearchParams({ tab: "all" });
    if (q.trim()) params.set("q", q.trim());
    router.push(`/jobs?${params}`);
  };

  return (
    <>
      <header className="command-bar">
        <div>
          <h1>Welcome, {me.first_name}</h1>
          <p className="muted">
            {setupDone ? "Here's where your job search stands today." : "Three steps and BrewMyJob starts scoring your job alerts."}
          </p>
        </div>
        <form className="command-search" role="search" onSubmit={search}>
          <Icon name="search" />
          <input className="input" type="search" placeholder="Search your jobs: role, company, skill…" aria-label="Search your jobs"
            value={q} onChange={(e) => setQ(e.target.value)} />
        </form>
        <div className="row">
          <Link className="btn" href="/inbox"><Icon name="upload" />Add an alert email</Link>
          <Link className="btn btn-primary" href="/jobs"><Icon name="briefcase" />Open jobs</Link>
        </div>
      </header>

      {!cand.job_locations.length ? (
        <JobLocationsAsk onSaved={(c) => setData((d) => (d ? { ...d, cand: c } : d))} />
      ) : null}

      {stats.needs_input > 0 || due.follow_ups_due > 0 ? (
        <section className="action-banner" aria-label="Needs you">
          <span className="action-icon"><Icon name="spark" size={20} /></span>
          <div className="grow">
            <h2>
              {[
                stats.needs_input ? `${stats.needs_input} top match${stats.needs_input > 1 ? "es need" : " needs"} your input` : "",
                due.follow_ups_due ? `${due.follow_ups_due} follow-up${due.follow_ups_due > 1 ? "s" : ""} due` : "",
              ].filter(Boolean).join(" · ")}
            </h2>
            <p className="muted">
              {stats.needs_input
                ? "Answer the open questions (notice period, CTC, a missing skill) and those jobs become ready to apply."
                : "Applications waiting for a follow-up from you."}
            </p>
          </div>
          <div className="row">
            {stats.needs_input ? <Link className="btn btn-primary btn-sm" href="/jobs?readiness=needs_input">Resolve them</Link> : null}
            {due.follow_ups_due ? <Link className="btn btn-sm" href="/applications">Open follow-ups</Link> : null}
          </div>
        </section>
      ) : null}

      <div className="relay-bar">
        <span className="relay-label">Your forwarding address</span>
        <button type="button" className="relay-token" onClick={copy} title="Copy the address">
          <code data-testid="forwarding-address">{me.forwarding_address}</code>
          <Icon name="copy" size={14} />
          <span className="relay-copied" aria-live="polite">{copied ? "Copied" : ""}</span>
        </button>
        <span className="relay-status">
          {mail.receiving && mail.last_received_at ? (
            <>Last alert: <b className="good-text">{seenAgo(mail.last_received_at).toLowerCase()}</b></>
          ) : (
            <>No alert received yet · <Link href="/settings/mail">How to set it up</Link></>
          )}
        </span>
      </div>

      {!setupDone ? <SetupSteps steps={steps} completeness={cand.completeness} profiles={profiles} /> : null}

      <section className="kpi-grid" data-testid="jobs-card" aria-label="Your numbers">
        <div className="kpi">
          <div className="kpi-head"><span>Active jobs</span><Icon name="briefcase" /></div>
          <div className="kpi-value num">{stats.active}</div>
          <div className="kpi-desc">
            <b className="good-text">{stats.new} new</b> · {stats.last_7_days} in the last 7 days · {stats.applied} applied · {stats.expired} expired
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-head"><span>Top matches</span><Icon name="check" /></div>
          <div className="kpi-value num good-text">{stats.top}</div>
          <div className="kpi-desc">
            <Link href="/jobs?readiness=ready" data-testid="ready">{stats.ready} ready to apply</Link> ·{" "}
            <Link href="/jobs?readiness=needs_input" data-testid="needs-input">{stats.needs_input} need your input</Link>
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-head"><span>Open applications</span><Icon name="send" /></div>
          <div className="kpi-value num">{openApps}</div>
          <div className="kpi-desc">
            {OPEN.map((k) => `${recent.counts[k] ?? 0} ${APPLICATION_STATUS[k]!.label.toLowerCase()}`).join(" · ")}
          </div>
        </div>
      </section>

      <div className="dash-grid">
        <div className="stack" style={{ gap: 24 }}>
          <section>
            <div className="section-head">
              <h2>Top matches</h2>
              {stats.needs_input ? <span className="badge badge-warn">{stats.needs_input} need your input</span> : null}
              <span className="spacer" />
              <Link className="btn btn-sm" href="/jobs">See all ({stats.top})</Link>
            </div>
            {top.length ? (
              <ul className="job-list">
                {top.map((j) => <TopJob key={j.id} j={j} />)}
              </ul>
            ) : (
              <div className="card empty">
                <h3>No top matches yet</h3>
                <p className="muted">
                  {stats.active ? "Your jobs are below your match threshold for now. Other jobs are on the Jobs page." : "Forward a job-alert email and its jobs are scored here."}
                </p>
              </div>
            )}
          </section>

          <section className="card" data-testid={due.follow_ups_due > 0 ? "follow-ups" : undefined}>
            <div className="section-head">
              <h2>Pipeline <span className="subtle">{openApps} open</span></h2>
              <span className="spacer" />
              <Link className="btn btn-sm" href="/applications">Open Applications</Link>
            </div>
            <Pipeline due={due.items} recent={recent.items} />
          </section>
        </div>

        <aside className="stack" style={{ gap: 20 }} aria-label="Summary">
          <section className="card">
            <div className="section-head"><h3>Match funnel</h3></div>
            <ul className="funnel">
              <FunnelRow label="Active jobs" value={stats.active} of={stats.active} color="var(--ink-3)" />
              <FunnelRow label="Scored" value={scored} of={stats.active} color="var(--info)" />
              <FunnelRow label="Top matches" value={stats.top} of={stats.active} color="var(--acc)" />
              <FunnelRow label="Ready to apply" value={stats.ready} of={stats.active} color="var(--good)" />
            </ul>
            <p className="subtle" style={{ marginTop: 12 }}>
              {stats.other} below your threshold are under Other jobs{stats.unscored ? `; ${stats.unscored} wait for a score` : ""}.
            </p>
          </section>

          <section className="claim-card">
            <strong><Icon name="shield" /> Nothing made up</strong>
            <p>
              Tailored resumes and cover letters are checked against your own resumes: a claim they don&apos;t
              support is left out. And you always submit the application yourself.
            </p>
          </section>
        </aside>
      </div>
    </>
  );
}

function TopJob({ j }: { j: UserJob }) {
  const m = j.match;
  const band = m ? BAND[m.band] : null;
  const sources = sourceLabels(j.job.sources, j.job.company);
  return (
    <li className="card job-card">
      <div className={`score ${band ? `score-${band.kind}` : "score-none"}`} title={band?.label}>{m ? m.score : "–"}</div>
      <div className="job-main">
        <div className="row" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
          <div className="grow" style={{ minWidth: 0 }}>
            <Link className="job-title" href={`/jobs/${j.id}`}>{j.job.title}</Link>
            <div className="job-meta">
              <b>{j.job.company ?? "Company not named"}</b>
              {j.job.location ? <span><Icon name="pin" size={13} />{[j.job.location, j.job.work_model].filter(Boolean).join(" · ")}</span> : null}
            </div>
          </div>
          <Link className="btn btn-primary btn-sm" href={`/jobs/${j.id}`}>Open</Link>
        </div>
        <div className="chip-row">
          {j.job.salary ? <span className="badge">{j.job.salary}</span> : null}
          {sources.length ? <span className="badge"><Icon name="link" size={12} />{sources.join(" + ")}</span> : null}
          {j.readiness?.status === "ready" ? <span className="badge badge-good"><Icon name="check" size={12} />Ready to apply</span> : null}
          {j.readiness?.status === "needs_input" ? (
            <span className="badge badge-warn"><Icon name="alert" size={12} />Needs input ({j.readiness.blockers})</span>
          ) : null}
          {j.readiness?.status === "manual_only" ? <span className="badge badge-warn">Manual steps</span> : null}
          {m?.best_resume_label ? <span className="badge badge-info">Use: {m.best_resume_label}</span> : null}
          {m?.provisional ? <span className="badge">From the alert only</span> : null}
          {j.possible_duplicate ? <span className="badge badge-warn">Possible duplicate</span> : null}
        </div>
        <span className="subtle">{seenAgo(j.first_seen_at)}{j.job.experience ? ` · ${j.job.experience}` : ""}</span>
      </div>
    </li>
  );
}

function Pipeline({ due, recent }: { due: Application[]; recent: Application[] }) {
  const dueIds = new Set(due.map((a) => a.id));
  const items = [...due, ...recent.filter((a) => !dueIds.has(a.id) && (OPEN as readonly string[]).includes(a.status))].slice(0, 6);
  if (!items.length) return <p className="muted">No open applications. When you apply for a job, mark it Applied and it shows here.</p>;
  const day = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  return (
    <ul className="stage-grid">
      {items.map((a) => {
        const st = APPLICATION_STATUS[a.status];
        return (
          <li key={a.id} className={`stage ${a.follow_up_due ? "due" : ""}`}>
            <div className="stage-top">
              <span className="stage-title">{a.follow_up_due ? "Follow-up due" : st?.label ?? a.status}</span>
              {a.follow_up_due ? <Icon name="alert" size={14} /> : null}
            </div>
            <Link href={`/applications?open=${a.id}`} className="stage-company">{a.job.company ?? "Company not named"}</Link>
            <span className="stage-role">{a.job.title}</span>
            <span className="subtle">
              {a.follow_up_due && a.follow_up_on ? `Follow up planned for ${day(a.follow_up_on)}` : `Applied ${day(a.applied_on)}`}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function FunnelRow({ label, value, of, color }: { label: string; value: number; of: number; color: string }) {
  const pct = of ? Math.round((100 * value) / of) : 0;
  return (
    <li className="funnel-row">
      <span className="funnel-label">{label}</span>
      <span className="funnel-track" aria-hidden="true"><i style={{ width: `${pct}%`, background: color }} /></span>
      <span className="funnel-val num">{value}</span>
    </li>
  );
}

function SetupSteps({ steps, completeness, profiles }: {
  steps: { profile: boolean; search: boolean; mail: boolean };
  completeness: number;
  profiles: SearchProfile[];
}) {
  return (
    <section className="card setup">
      <div className="section-head"><h2>Get set up</h2><span className="subtle">{[steps.profile, steps.search, steps.mail].filter(Boolean).length} of 3 done</span></div>
      <ol className="steps">
        <li className={`step ${steps.profile ? "done" : ""}`}>
          <span className="step-dot">{steps.profile ? "✓" : 1}</span>
          <div className="step-body">
            <h3>Add your resume and complete your profile</h3>
            <p className="muted">Upload your resume to fill your profile and score every job. Then check skills, notice period and expected CTC.</p>
            <div className="row" style={{ marginTop: 6 }}>
              <div className="meter" style={{ width: 160 }}><i style={{ width: `${completeness}%` }} /></div>
              <span className="subtle num">{completeness}%</span>
              <Link className="btn btn-sm" href="/profile">{steps.profile ? "Review" : "Continue"}</Link>
            </div>
          </div>
        </li>
        <li className={`step ${steps.search ? "done" : ""}`}>
          <span className="step-dot">{steps.search ? "✓" : 2}</span>
          <div className="step-body">
            <h3>Check your Skill Match profiles</h3>
            <p className="muted">
              {steps.search
                ? `Each resume has one, made from it: ${profiles.filter((p) => p.resume_id).map((p) => p.name).join(", ") || profiles.map((p) => p.name).join(", ")}. Check the roles and cities you want, and add skills the resume doesn't list.`
                : "Each resume you add gets a Skill Match profile made from it: the roles it's for, the cities, and its skills. You then set what you want next."}
            </p>
            <div className="row" style={{ marginTop: 6 }}>
              <Link className="btn btn-sm" href="/profile?tab=match">{steps.search ? "Review" : "Open"}</Link>
            </div>
          </div>
        </li>
        <li className={`step ${steps.mail ? "done" : ""}`}>
          <span className="step-dot">{steps.mail ? "✓" : 3}</span>
          <div className="step-body">
            <h3>Forward your LinkedIn and Naukri job alerts</h3>
            <p className="muted">
              {steps.mail
                ? "Alerts are arriving. Each one's jobs land on the Jobs page."
                : "Set up a filter in Gmail or Outlook that forwards job-alert emails to your forwarding address above."}
            </p>
            <div className="row" style={{ marginTop: 6 }}>
              <Link className="btn btn-sm" href="/settings/mail">How to set it up</Link>
            </div>
          </div>
        </li>
      </ol>
    </section>
  );
}
