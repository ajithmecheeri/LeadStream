"use client";
import type { ProfilesMeta, SearchProfile } from "@fitfirst/api";
import { useCallback, useEffect, useState } from "react";
import { LearnedPreferences } from "@/components/LearnedPreferences";
import { SearchProfileEditor } from "@/components/SearchProfileEditor";
import { errorMessage, Notice } from "@/components/ui";
import { api } from "@/lib/api";

/** The Skill Match Profile tab (user feedback 2026-11-13): one profile per resume, made from it. The resume's
 *  skills refresh with it; the skills you add stay, and the ones the resume doesn't show yet are flagged so you
 *  can add them to the resume itself. */
export function MatchProfiles({ onOpenProfileTab }: { onOpenProfileTab: () => void }) {
  const [items, setItems] = useState<SearchProfile[] | null>(null);
  const [meta, setMeta] = useState<ProfilesMeta | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "good" | "bad"; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, m] = await Promise.all([api.profiles(), api.profilesMeta()]);
      setItems(p);
      setMeta(m);
    } catch (e) {
      setMsg({ kind: "bad", text: errorMessage(e) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function refresh(p: SearchProfile) {
    setBusy(p.id);
    setMsg(null);
    try {
      const after = await api.refreshProfile(p.id);
      setItems((xs) => xs && xs.map((x) => (x.id === p.id ? after : x)));
      setMsg({ kind: "good", text: `Skills read again from “${after.resume_label}”. Your jobs are being scored again.` });
    } catch (e) {
      setMsg({ kind: "bad", text: errorMessage(e) });
    } finally {
      setBusy(null);
    }
  }

  if (!items || !meta) return msg ? <Notice kind="bad">{msg.text}</Notice> : <div className="loading">Loading…</div>;
  const own = items.filter((p) => p.resume_id);
  const shared = items.filter((p) => !p.resume_id);

  return (
    <div className="stack" style={{ gap: 16 }}>
      <p className="muted">
        Each resume has its own Skill Match profile: the roles, places and skills that resume is matched with. Its
        skills come from the resume and refresh whenever you replace the resume; the skills you add stay.
      </p>
      {msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null}
      {own.length === 0 ? (
        <div className="card empty">
          <h3>No resume yet</h3>
          <p className="muted">Upload a resume on the Profile tab. Its Skill Match profile is made from it.</p>
          <button type="button" className="btn btn-primary btn-sm" onClick={onOpenProfileTab}>Go to Profile</button>
        </div>
      ) : null}
      {own.map((p) =>
        editing === p.id ? (
          <SearchProfileEditor key={p.id} id={p.id} onDone={() => { setEditing(null); void load(); }} />
        ) : (
          <MatchProfileCard key={p.id} p={p} meta={meta} busy={busy === p.id} onRefresh={() => refresh(p)}
            onEdit={() => setEditing(p.id)} onOpenProfileTab={onOpenProfileTab} />
        ),
      )}
      {shared.length ? (
        <>
          <h2 style={{ marginTop: 8 }}>Profiles for every resume</h2>
          <p className="subtle" style={{ marginTop: -8 }}>Made before profiles came from resumes; each judges all your resumes.</p>
          {shared.map((p) =>
            editing === p.id ? (
              <SearchProfileEditor key={p.id} id={p.id} onDone={() => { setEditing(null); void load(); }} />
            ) : (
              <MatchProfileCard key={p.id} p={p} meta={meta} busy={false} onEdit={() => setEditing(p.id)} />
            ),
          )}
        </>
      ) : null}
      <LearnedPreferences />
    </div>
  );
}

function MatchProfileCard({ p, meta, busy, onRefresh, onEdit, onOpenProfileTab }: {
  p: SearchProfile;
  meta: ProfilesMeta;
  busy: boolean;
  onRefresh?: () => void;
  onEdit: () => void;
  onOpenProfileTab?: () => void;
}) {
  const fromResume = p.resume_skills ?? [];
  const missing = p.not_in_resume ?? [];
  return (
    <section className="card match-profile" data-testid="match-profile">
      <div className="card-head">
        <div className="stack-tight">
          <h2>{p.name}</h2>
          {p.resume_label ? <span className="subtle">From the resume “{p.resume_label}”</span> : null}
        </div>
        <div className="row">
          <span className={`badge ${p.active ? "badge-good" : ""}`}>{p.active ? "Active" : "Paused"}</span>
          {onRefresh ? (
            <button type="button" className="btn btn-sm" disabled={busy} onClick={onRefresh}
              title="Read the resume's skills again. Skills you added stay.">{busy ? "Refreshing…" : "Refresh from resume"}</button>
          ) : null}
          <button type="button" className="btn btn-sm btn-primary" onClick={onEdit} aria-label={`Edit ${p.name}`}>Edit</button>
        </div>
      </div>

      {missing.length ? (
        <div className="todo" style={{ marginBottom: 12 }} data-testid="out-of-sync">
          <strong>Out of sync with the resume:</strong> you added {missing.length === 1 ? "a skill" : `${missing.length} skills`} the
          resume doesn&apos;t show yet: {missing.join(", ")}. Add {missing.length === 1 ? "it" : "them"} to the resume, then use{" "}
          <em>Replace file</em> on the{" "}
          {onOpenProfileTab ? <button type="button" className="link-button" onClick={onOpenProfileTab}>Profile tab</button> : "Profile tab"}
          {" "}so tailored resumes can claim {missing.length === 1 ? "it" : "them"}.
        </div>
      ) : null}
      {p.resume_id && !fromResume.length ? (
        <div className="todo" style={{ marginBottom: 12 }}>
          No skills section found in this resume. Add a &ldquo;Skills&rdquo; section to it, or add skills here with Edit.
        </div>
      ) : null}

      <dl className="kv">
        <dt>Roles</dt><dd>{p.target_roles.length ? p.target_roles.join(", ") : <span className="subtle">None yet: add them with Edit</span>}</dd>
        <dt>Locations</dt><dd>{p.locations.length ? p.locations.join(", ") : "Anywhere"} · {p.work_models.join("/")}</dd>
        <dt>Seniority</dt><dd>{meta.seniority[String(p.min_seniority)] ?? p.min_seniority}+</dd>
        <dt>Threshold</dt><dd className="num">{p.threshold}</dd>
      </dl>

      {p.resume_id ? (
        <div style={{ marginTop: 14 }}>
          <div className="label">Skills from the resume ({fromResume.length})</div>
          <div className="chip-row" data-testid="resume-skills">
            {fromResume.map((s) => <span key={s} className="badge">{s}</span>)}
          </div>
        </div>
      ) : null}
      <div style={{ marginTop: 10 }}>
        <div className="label">Skills you added ({p.skills.length})</div>
        <div className="chip-row" data-testid="added-skills">
          {p.skills.length
            ? p.skills.map((s) => (
              <span key={s} className={`badge ${missing.includes(s) ? "badge-warn" : "badge-info"}`}
                title={missing.includes(s) ? "Not in the resume yet" : undefined}>{s}</span>
            ))
            : <span className="subtle">None. Add them with Edit, or from a job&apos;s missing skills.</span>}
        </div>
      </div>
    </section>
  );
}
