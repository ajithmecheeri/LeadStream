"use client";
import type { ApplyProfile, EducationEntry, WorkEntry } from "@fitfirst/api";
import { useEffect, useState, type FormEvent } from "react";
import { errorMessage, Field, fieldErrors, Notice } from "@/components/ui";
import { api } from "@/lib/api";

type Lang = NonNullable<ApplyProfile["languages"]>[number];
type Form = {
  phone: string;
  address_line1: string;
  address_line2: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  websites: string;
  languages: Lang[];
  work_history: WorkEntry[];
  education: EducationEntry[];
};
const PROFICIENCY = ["basic", "conversational", "fluent", "native"] as const;

const s = (v: string | null | undefined) => v ?? "";
const orNull = (v: string) => (v.trim() ? v.trim() : null);
// While typing: keep the text as typed (trimming each keystroke ate the space in "Master's Degree", user
// 2026-11-10); `tidy` trims it on Save.
const typed = (v: string) => (v.trim() ? v : null);
function tidy<T extends object>(entry: T): T {
  return Object.fromEntries(
    Object.entries(entry).map(([k, v]) => [k, typeof v === "string" ? (v.trim() || null) : v]),
  ) as T;
}

function toForm(p: ApplyProfile): Form {
  return {
    phone: s(p.phone),
    address_line1: s(p.address_line1),
    address_line2: s(p.address_line2),
    city: s(p.city),
    state: s(p.state),
    postal_code: s(p.postal_code),
    country: s(p.country),
    websites: (p.websites ?? []).join("\n"),
    languages: p.languages ?? [],
    work_history: p.work_history ?? [],
    education: p.education ?? [],
  };
}

/** Milestone 14.1: what application forms ask for beyond the profile. Feeds the Apply kit on every job and the
 * browser extension. "Fill work history from a resume" proposes; nothing is saved until Save. */
export function ApplyProfileForm() {
  const [profile, setProfile] = useState<ApplyProfile | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [resumes, setResumes] = useState<{ id: string; label: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "good" | "bad" | "info"; text: string } | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    api.applyProfile().then((p) => { setProfile(p); setForm(toForm(p)); }).catch((e) => setMsg({ kind: "bad", text: errorMessage(e) }));
    api.resumes().then((rs) => setResumes(rs.items.map((r) => ({ id: r.id, label: r.label })))).catch(() => undefined);
  }, []);

  if (!form || !profile) return <section className="card" id="apply"><p className="subtle">{msg?.text ?? "Loading…"}</p></section>;

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => (f ? { ...f, [k]: v } : f));
  const setWork = (i: number, patch: Partial<WorkEntry>) =>
    setForm((f) => (f ? { ...f, work_history: f.work_history.map((w, j) => (j === i ? { ...w, ...patch } : w)) } : f));
  const setEdu = (i: number, patch: Partial<EducationEntry>) =>
    setForm((f) => (f ? { ...f, education: f.education.map((e, j) => (j === i ? { ...e, ...patch } : e)) } : f));
  const setLang = (i: number, patch: Partial<Lang>) =>
    setForm((f) => (f ? { ...f, languages: f.languages.map((l, j) => (j === i ? { ...l, ...patch } : l)) } : f));

  async function fill(resumeId: string) {
    if (!resumeId) return;
    setBusy(true);
    setMsg(null);
    try {
      const d = await api.applyDraft(resumeId);
      setForm((f) =>
        f
          ? {
              ...f,
              phone: f.phone || s(d.phone),
              city: f.city || s(d.city),
              // A role already in the form keeps what the user typed (location, description); the resume fills
              // what is empty.
              work_history: d.work_history?.length
                ? d.work_history.map((w) => {
                    const same = f.work_history.find(
                      (o) => o.title.toLowerCase() === w.title.toLowerCase() && (o.company ?? "").toLowerCase() === (w.company ?? "").toLowerCase(),
                    );
                    return same
                      ? { ...w, location: same.location || w.location, description: same.description || w.description, current: same.current || w.current }
                      : w;
                  })
                : f.work_history,
              education: d.education?.length ? d.education : f.education,
            }
          : f,
      );
      setMsg({
        kind: "info",
        text: `Read ${d.work_history?.length ?? 0} roles and ${d.education?.length ?? 0} education entries from the resume. Check them, add locations and descriptions, then Save.`,
      });
    } catch (e) {
      setMsg({ kind: "bad", text: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form || !profile) return;
    setBusy(true);
    setMsg(null);
    setErrors({});
    try {
      const saved = await api.saveApplyProfile({
        phone: orNull(form.phone),
        address_line1: orNull(form.address_line1),
        address_line2: orNull(form.address_line2),
        city: orNull(form.city),
        state: orNull(form.state),
        postal_code: orNull(form.postal_code),
        country: orNull(form.country),
        websites: form.websites.split(/\s+/).filter(Boolean),
        languages: form.languages.filter((l) => l.language.trim()).map(tidy),
        work_history: form.work_history.filter((w) => w.title.trim()).map(tidy),
        education: form.education.filter((x) => x.school.trim()).map(tidy),
        version: profile.version,
      });
      setProfile(saved);
      setForm(toForm(saved));
      setMsg({ kind: "good", text: "Saved. The Apply kit on every job uses it now." });
    } catch (err) {
      setErrors(fieldErrors(err));
      setMsg({ kind: "bad", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card stack" id="apply" style={{ scrollMarginTop: 16 }} onSubmit={save} noValidate data-testid="apply-profile">
      <div className="card-head">
        <h2>For application forms</h2>
        <span className="subtle">Workday and other company forms ask for these</span>
      </div>
      <p className="hint" style={{ marginTop: 0 }}>
        Used by the Apply kit on each job (copy field by field) and the browser extension. Your name and email come from your account.
      </p>
      {msg && msg.kind !== "info" ? <Notice kind={msg.kind}>{msg.text}</Notice> : null}

      <div className="grid-2">
        <Field label="Phone" htmlFor="ap-phone" error={errors.phone}>
          <input id="ap-phone" className="input" autoComplete="tel" value={form.phone} onChange={(e) => set("phone", e.target.value)} placeholder="+91 98765 43210" />
        </Field>
        <Field label="Country" htmlFor="ap-country" error={errors.country}>
          <input id="ap-country" className="input" value={form.country} onChange={(e) => set("country", e.target.value)} placeholder="India" />
        </Field>
        <Field label="Address line 1" htmlFor="ap-a1" error={errors.address_line1} className="span-all">
          <input id="ap-a1" className="input" value={form.address_line1} onChange={(e) => set("address_line1", e.target.value)} />
        </Field>
        <Field label="Address line 2" htmlFor="ap-a2" error={errors.address_line2} className="span-all">
          <input id="ap-a2" className="input" value={form.address_line2} onChange={(e) => set("address_line2", e.target.value)} />
        </Field>
        <Field label="City" htmlFor="ap-city" error={errors.city}>
          <input id="ap-city" className="input" value={form.city} onChange={(e) => set("city", e.target.value)} />
        </Field>
        <Field label="State" htmlFor="ap-state" error={errors.state}>
          <input id="ap-state" className="input" value={form.state} onChange={(e) => set("state", e.target.value)} />
        </Field>
        <Field label="Postal code" htmlFor="ap-pin" error={errors.postal_code}>
          <input id="ap-pin" className="input" value={form.postal_code} onChange={(e) => set("postal_code", e.target.value)} />
        </Field>
        <Field label="Websites" htmlFor="ap-web" error={errors.websites} hint="One per line: portfolio, GitHub, blog">
          <textarea id="ap-web" className="textarea" rows={2} value={form.websites} onChange={(e) => set("websites", e.target.value)} />
        </Field>
      </div>

      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", justifyContent: "space-between", marginTop: 8 }}>
        <h3 style={{ margin: 0 }}>Work history <span className="subtle">most recent first</span></h3>
        {resumes.length ? (
          // Next to the list it fills (user, 2026-11-10: at the top of the card it was missed). Always back to
          // "Choose…", so picking the same resume again reads it again.
          <label style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span>Fill work history from a resume</span>
            <select className="select narrow" aria-label="Fill work history from a resume" value="" disabled={busy} onChange={(e) => void fill(e.target.value)}>
              <option value="">Choose…</option>
              {resumes.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
            </select>
          </label>
        ) : null}
      </div>
      {msg?.kind === "info" ? <Notice kind="info">{msg.text}</Notice> : null}
      {form.work_history.map((w, i) => (
        <fieldset key={i} className="stack apply-entry" data-testid="work-entry">
          <legend className="sr-only">Role {i + 1}</legend>
          <div className="grid-2">
            <Field label="Job title" htmlFor={`w${i}-t`} error={errors[`work_history.${i}.title`]}>
              <input id={`w${i}-t`} className="input" value={w.title} onChange={(e) => setWork(i, { title: e.target.value })} />
            </Field>
            <Field label="Company" htmlFor={`w${i}-c`}>
              <input id={`w${i}-c`} className="input" value={s(w.company)} onChange={(e) => setWork(i, { company: typed(e.target.value) })} />
            </Field>
            <Field label="Location" htmlFor={`w${i}-l`}>
              <input id={`w${i}-l`} className="input" value={s(w.location)} onChange={(e) => setWork(i, { location: typed(e.target.value) })} />
            </Field>
            <div style={{ display: "flex", gap: 8 }}>
              <Field label="From" htmlFor={`w${i}-s`} error={errors[`work_history.${i}.start`]}>
                <input id={`w${i}-s`} className="input" type="month" value={s(w.start)} onChange={(e) => setWork(i, { start: typed(e.target.value) })} />
              </Field>
              <Field label="To" htmlFor={`w${i}-e`} error={errors[`work_history.${i}.end`]}>
                <input id={`w${i}-e`} className="input" type="month" disabled={w.current} value={s(w.end)} onChange={(e) => setWork(i, { end: typed(e.target.value) })} />
              </Field>
            </div>
            <label className="span-all" style={{ display: "flex", gap: 8 }}>
              <input type="checkbox" checked={!!w.current} onChange={(e) => setWork(i, { current: e.target.checked, end: e.target.checked ? null : w.end })} />
              I currently work here
            </label>
            <Field label="Role description" htmlFor={`w${i}-d`} className="span-all">
              <textarea id={`w${i}-d`} className="textarea" rows={3} value={s(w.description)} onChange={(e) => setWork(i, { description: typed(e.target.value) })} />
            </Field>
          </div>
          <button type="button" className="btn btn-sm btn-ghost" style={{ justifySelf: "start" }}
            onClick={() => set("work_history", form.work_history.filter((_, j) => j !== i))}>Remove role</button>
        </fieldset>
      ))}
      <button type="button" className="btn btn-sm" style={{ justifySelf: "start" }}
        onClick={() => set("work_history", [...form.work_history, { title: "", current: false }])}>Add a role</button>

      <h3 style={{ margin: "8px 0 0" }}>Education</h3>
      {form.education.map((x, i) => (
        <fieldset key={i} className="stack apply-entry" data-testid="education-entry">
          <legend className="sr-only">Education {i + 1}</legend>
          <div className="grid-2">
            <Field label="School or university" htmlFor={`e${i}-s`}>
              <input id={`e${i}-s`} className="input" value={x.school} onChange={(e) => setEdu(i, { school: e.target.value })} />
            </Field>
            <Field label="Degree" htmlFor={`e${i}-d`}>
              <input id={`e${i}-d`} className="input" value={s(x.degree)} onChange={(e) => setEdu(i, { degree: typed(e.target.value) })} />
            </Field>
            <Field label="Field of study" htmlFor={`e${i}-f`}>
              <input id={`e${i}-f`} className="input" value={s(x.field)} onChange={(e) => setEdu(i, { field: typed(e.target.value) })} />
            </Field>
            <div style={{ display: "flex", gap: 8 }}>
              <Field label="From (year)" htmlFor={`e${i}-a`}>
                <input id={`e${i}-a`} className="input num" type="number" min={1950} max={2100} value={x.start_year ?? ""}
                  onChange={(e) => setEdu(i, { start_year: e.target.value ? Number(e.target.value) : null })} />
              </Field>
              <Field label="To (year)" htmlFor={`e${i}-b`}>
                <input id={`e${i}-b`} className="input num" type="number" min={1950} max={2100} value={x.end_year ?? ""}
                  onChange={(e) => setEdu(i, { end_year: e.target.value ? Number(e.target.value) : null })} />
              </Field>
            </div>
          </div>
          <button type="button" className="btn btn-sm btn-ghost" style={{ justifySelf: "start" }}
            onClick={() => set("education", form.education.filter((_, j) => j !== i))}>Remove</button>
        </fieldset>
      ))}
      <button type="button" className="btn btn-sm" style={{ justifySelf: "start" }}
        onClick={() => set("education", [...form.education, { school: "" }])}>Add education</button>

      <h3 style={{ margin: "8px 0 0" }}>Languages</h3>
      {form.languages.map((l, i) => (
        <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input className="input" style={{ maxWidth: 220 }} aria-label={`Language ${i + 1}`} value={l.language} onChange={(e) => setLang(i, { language: e.target.value })} />
          <select className="select narrow" aria-label={`Proficiency in language ${i + 1}`} value={l.proficiency ?? ""}
            onChange={(e) => setLang(i, { proficiency: (e.target.value || null) as Lang["proficiency"] })}>
            <option value="">Proficiency…</option>
            {PROFICIENCY.map((p) => <option key={p} value={p}>{p[0]!.toUpperCase() + p.slice(1)}</option>)}
          </select>
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => set("languages", form.languages.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <button type="button" className="btn btn-sm" style={{ justifySelf: "start" }}
        onClick={() => set("languages", [...form.languages, { language: "" }])}>Add a language</button>

      <div><button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Save for application forms"}</button></div>
    </form>
  );
}
