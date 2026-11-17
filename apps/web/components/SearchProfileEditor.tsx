"use client";
import type { ProfilesMeta, SearchProfile } from "@fitfirst/api";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { ChipsInput, errorMessage, Field, fieldErrors, Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { setWeight, total } from "@/lib/weights";

type WorkModel = "Remote" | "Hybrid" | "On-site";
type Form = {
  name: string; target_roles: string[]; locations: string[]; work_models: WorkModel[]; min_seniority: number;
  excluded_companies: string[]; skills: string[]; weights: Record<string, number>; threshold: number; active: boolean;
};

/** Edit a Skill Match profile. With `onDone` it sits inside the Skill Match Profile tab (2026-11-13): no page
 *  title, and Save / Cancel / Delete hand back to the tab. */
export function SearchProfileEditor({ id, onDone }: { id?: string; onDone?: () => void }) {
  const router = useRouter();
  const done = () => (onDone ? onDone() : router.push("/profile?tab=match"));
  const [meta, setMeta] = useState<ProfilesMeta | null>(null);
  const [existing, setExisting] = useState<SearchProfile | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const m = await api.profilesMeta();
        setMeta(m);
        if (id) {
          const p = await api.profile(id);
          setExisting(p);
          setForm({ ...p, work_models: p.work_models as WorkModel[], excluded_companies: p.excluded_companies ?? [],
            skills: p.skills ?? [], weights: p.weights ?? m.default_weights, threshold: p.threshold ?? 85, active: p.active ?? true });
        } else {
          setForm({ name: "", target_roles: [], locations: [], work_models: ["Hybrid", "Remote"], min_seniority: 5,
            excluded_companies: [], skills: [], weights: { ...m.default_weights }, threshold: 85, active: true });
        }
      } catch (e) {
        setError(errorMessage(e));
      }
    })();
  }, [id]);

  if (error && !form) return <Notice kind="bad">{error}</Notice>;
  if (!form || !meta) return <div className="loading">Loading…</div>;
  // Functional updates: a chip added on blur and a slider change can land in the same tick.
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => (f ? { ...f, [k]: v } : f));
  const sum = total(form.weights);
  const toggleWm = (wm: WorkModel) =>
    setForm((f) => f && { ...f, work_models: f.work_models.includes(wm) ? f.work_models.filter((x) => x !== wm) : [...f.work_models, wm] });

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setBusy(true);
    setError(null);
    setErrors({});
    try {
      if (existing) await api.updateProfile(existing.id, { ...form, version: existing.version });
      else await api.createProfile(form);
      done();
    } catch (err) {
      setErrors(fieldErrors(err));
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  async function remove() {
    if (!existing || !window.confirm(`Delete "${existing.name}"? Jobs already scored for it will lose their scores.`)) return;
    setBusy(true);
    try {
      await api.deleteProfile(existing.id);
      done();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} noValidate data-testid="match-profile-editor">
      {onDone ? (
        <div className="section-head"><h2>Edit “{existing?.name ?? "profile"}”</h2>
          {existing?.resume_label ? <span className="subtle">From the resume “{existing.resume_label}”</span> : null}</div>
      ) : (
        <PageHeader title={existing ? existing.name : "New Skill Match profile"}
          sub="The roles, places and skills a resume is matched with." />
      )}
      {error ? <div style={{ marginBottom: 16 }}><Notice kind="bad">{error}</Notice></div> : null}

      <section className="card">
        <div className="card-head"><h2>Target</h2></div>
        <div className="grid-2">
          <Field label="Profile name" htmlFor="name" error={errors.name}>
            <input id="name" className="input" value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="VP Engineering" />
          </Field>
          <Field label="Minimum seniority" htmlFor="sen" error={errors.min_seniority} hint="Jobs below this level are filtered out.">
            <select id="sen" className="select" value={form.min_seniority} onChange={(e) => set("min_seniority", Number(e.target.value))}>
              {Object.entries(meta.seniority).map(([k, v]) => <option key={k} value={k}>{k} · {v}</option>)}
            </select>
          </Field>
          <Field label="Target roles" htmlFor="roles" error={errors.target_roles} className="span-all">
            <ChipsInput id="roles" value={form.target_roles} onChange={(v) => set("target_roles", v)} placeholder="VP Engineering, Head of Engineering…" />
          </Field>
          <Field label="Locations" htmlFor="locs" error={errors.locations}>
            <ChipsInput id="locs" value={form.locations} onChange={(v) => set("locations", v)} placeholder="Bengaluru, Remote…" />
          </Field>
          <div className="field">
            <span className="label">Work model</span>
            <div className="toggle-group" role="group" aria-label="Work model">
              {(meta.work_models as WorkModel[]).map((wm) => (
                <button type="button" key={wm} aria-pressed={form.work_models.includes(wm)} onClick={() => toggleWm(wm)}>{wm}</button>
              ))}
            </div>
            {errors.work_models ? <span className="field-error">{errors.work_models}</span> : null}
          </div>
          <Field label={`Skills you added (${form.skills.length} of ${meta.max_skills ?? 40})`} htmlFor="skills" error={errors.skills} className="span-all"
            hint={`Skills you have that the resume doesn't list${existing?.resume_skills?.length ? ` (it lists ${existing.resume_skills.length}, read automatically)` : ""}. They count with the resume's own when matching; add them to the resume too. "Skills" under What matters most sets how much skills count (now ${form.weights.skills ?? 0} of 100).`}>
            <ChipsInput id="skills" value={form.skills} onChange={(v) => set("skills", v)} placeholder="Java, AWS, Kafka, Microservices, Team leadership…" />
            {form.skills.length && (form.weights.skills ?? 0) < meta.suggested_skills_weight ? (
              <button type="button" className="btn btn-sm" style={{ marginTop: 6, alignSelf: "flex-start" }}
                onClick={() => setForm((f) => (f ? { ...f, weights: setWeight(f.weights, "skills", meta.suggested_skills_weight) } : f))}>
                Make skills count more ({meta.suggested_skills_weight} of 100)
              </button>
            ) : null}
          </Field>
          <Field label="Exclude companies" htmlFor="excl" error={errors.excluded_companies} className="span-all"
            hint="Matched against the company name, e.g. your current employer or staffing agencies.">
            <ChipsInput id="excl" value={form.excluded_companies} onChange={(v) => set("excluded_companies", v)} />
          </Field>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>What matters most</h2>
          <span className="subtle">Moving one slider rebalances the others so the total stays 100</span>
        </div>
        <div className="weights">
          {Object.entries(meta.factors).map(([key, label]) => (
            <div className="weight-row" key={key}>
              <label htmlFor={`w-${key}`}>{label}</label>
              <input id={`w-${key}`} type="range" min={0} max={60} value={form.weights[key] ?? 0}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setForm((f) => (f ? { ...f, weights: setWeight(f.weights, key, v) } : f));
                }} />
              <output className="num" htmlFor={`w-${key}`}>{form.weights[key] ?? 0}</output>
            </div>
          ))}
          <div className="weight-total">
            <span>Total</span>
            <span className="num" style={{ color: sum === 100 ? "var(--good-text)" : "var(--bad-text)" }}>{sum} / 100</span>
          </div>
          {errors.weights ? <span className="field-error">{errors.weights}</span> : null}
          <div className="row">
            <button type="button" className="btn btn-sm" onClick={() => set("weights", { ...meta.default_weights })}>Reset to defaults</button>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-head"><h2>Alerts</h2></div>
        <div className="grid-2">
          <Field label={`Strong match threshold: ${form.threshold}`} htmlFor="thr" error={errors.threshold}
            hint="Jobs scoring at or above this are 'strong' and notify you right away.">
            <input id="thr" type="range" min={50} max={100} value={form.threshold} onChange={(e) => set("threshold", Number(e.target.value))} />
          </Field>
          <label className="check" style={{ alignSelf: "center" }}>
            <input type="checkbox" checked={form.active} onChange={(e) => set("active", e.target.checked)} />
            <span>Active: score new jobs against this profile</span>
          </label>
        </div>
      </section>

      <div className="sticky-actions">
        {existing && !existing.resume_id ? <button type="button" className="btn btn-danger" onClick={remove} disabled={busy}>Delete</button> : null}
        <span className="spacer" />
        <button type="button" className="btn" onClick={done}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || sum !== 100}>{busy ? "Saving…" : existing ? "Save changes" : "Create profile"}</button>
      </div>
    </form>
  );
}
