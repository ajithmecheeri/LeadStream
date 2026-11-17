"use client";
import type { Candidate, CandidateDraft } from "@fitfirst/api";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { DocumentLibrary } from "@/components/DocumentLibrary";
import { ApplicationQuestions } from "@/components/ApplicationQuestions";
import { AnswerBank } from "@/components/AnswerBank";
import { ApplyProfileForm } from "@/components/ApplyProfileForm";
import { MatchProfiles } from "@/components/MatchProfiles";
import { ChipsInput, errorMessage, Field, fieldErrors, Notice, PageHeader, toNumOrNull, toStrOrNull } from "@/components/ui";
import { api } from "@/lib/api";
import { splitPlaces } from "@/lib/places";

/** The Profile page's tabs (user feedback 2026-11-13): resumes, cover letters and facts; one Skill Match profile
 *  per resume (search profiles moved here); what application forms are filled with. Old links still land right:
 *  #resumes and #cover-letters open Profile, #learned Skill Match, #apply the autofill tab. */
type Tab = "profile" | "match" | "autofill" | "answers";
const TABS: { key: Tab; label: string }[] = [
  { key: "profile", label: "Profile" },
  { key: "match", label: "Skill Match Profile" },
  { key: "autofill", label: "Application Autofill Information" },
  { key: "answers", label: "Answer bank" },
];
const HASH_TAB: Record<string, Tab> = { resumes: "profile", "cover-letters": "profile", learned: "match", apply: "autofill" };

function tabFromUrl(): Tab {
  const q = new URLSearchParams(window.location.search).get("tab");
  if (q === "match" || q === "autofill" || q === "profile" || q === "answers") return q;
  return HASH_TAB[window.location.hash.slice(1)] ?? "profile";
}

const merge = (a: string[], b: string[]) => {
  const out = [...a];
  for (const x of b) if (!out.some((y) => y.toLowerCase() === x.toLowerCase())) out.push(x);
  return out;
};

type Form = {
  headline: string; summary: string; current_location: string; years_experience: string;
  domains: string[]; notice_days: string; current_ctc: string; expected_ctc: string;
  work_authorization: string; linkedin_url: string; job_locations: string;
};

const toForm = (c: Candidate): Form => ({
  headline: c.headline ?? "", summary: c.summary ?? "", current_location: c.current_location ?? "",
  years_experience: c.years_experience?.toString() ?? "", domains: c.domains,
  notice_days: c.notice_days?.toString() ?? "", current_ctc: c.current_ctc ?? "", expected_ctc: c.expected_ctc ?? "",
  work_authorization: c.work_authorization ?? "", linkedin_url: c.linkedin_url ?? "",
  job_locations: c.job_locations.join(", "),
});

export default function ProfilePage() {
  const [tab, setTab] = useState<Tab | null>(null);

  useEffect(() => {
    const t = tabFromUrl();
    setTab(t);
    const hash = window.location.hash.slice(1);
    // After the tab renders, bring a linked section (#resumes, #apply…) into view.
    if (hash) setTimeout(() => document.getElementById(hash)?.scrollIntoView({ block: "start" }), 300);
  }, []);

  const open = useCallback((t: Tab) => {
    setTab(t);
    window.history.replaceState(null, "", t === "profile" ? "/profile" : `/profile?tab=${t}`);
  }, []);

  return (
    <>
      <PageHeader title="Profile" sub="Your resumes, the Skill Match profile made from each, what application forms are filled with, and your answers to screening questions." />
      <div className="tabs" role="tablist" aria-label="Profile sections">
        {TABS.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} aria-pressed={tab === t.key}
            onClick={() => open(t.key)} data-testid={`tab-${t.key}`}>{t.label}</button>
        ))}
      </div>
      <div style={{ marginTop: 18 }}>
        {tab === "profile" ? <ProfileTab /> : null}
        {tab === "match" ? <MatchProfiles onOpenProfileTab={() => open("profile")} /> : null}
        {tab === "autofill" ? (
          <div className="stack" style={{ gap: 16 }}>
            <p className="muted">
              What BrewMyJob fills into company application forms (the Apply kit on a job, and the browser extension
              when you click it). Fill it from a resume, then check it. You always submit yourself.
            </p>
            <ApplyProfileForm />
            <ApplicationQuestions />
          </div>
        ) : null}
        {tab === "answers" ? <AnswerBank /> : null}
      </div>
    </>
  );
}

function ProfileTab() {
  const [cand, setCand] = useState<Candidate | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ kind: "good" | "bad"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const formTop = useRef<HTMLDivElement>(null);

  /** Put what a resume says into the form for review. Lists are merged; nothing is saved until "Save profile". */
  function fillFrom(d: CandidateDraft, label: string) {
    setForm((f) => f && {
      ...f,
      headline: d.headline ?? f.headline,
      summary: d.summary ?? f.summary,
      current_location: d.location ? d.location.split(",")[0]!.trim() : f.current_location,
      years_experience: d.years_experience?.toString() ?? f.years_experience,
      domains: merge(f.domains, d.domains ?? []),
      linkedin_url: d.linkedin_url ?? f.linkedin_url,
    });
    setErrors({});
    setMsg({
      kind: "good",
      text: `Filled from “${label}”${d.method === "rules" ? "" : " (read by AI)"}. Check the fields below, then Save profile.`,
    });
    formTop.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  useEffect(() => {
    api.candidate().then((c) => {
      setCand(c);
      setForm(toForm(c));
    }).catch((e) => setMsg({ kind: "bad", text: errorMessage(e) }));
  }, []);

  if (!form || !cand) return msg ? <Notice kind="bad">{msg.text}</Notice> : <div className="loading">Loading…</div>;
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => (f ? { ...f, [k]: v } : f));

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form || !cand) return;
    setBusy(true);
    setMsg(null);
    setErrors({});
    try {
      const saved = await api.saveCandidate({
        headline: toStrOrNull(form.headline), summary: toStrOrNull(form.summary),
        current_location: toStrOrNull(form.current_location), years_experience: toNumOrNull(form.years_experience),
        skills: cand.skills, domains: form.domains, notice_days: toNumOrNull(form.notice_days),
        current_ctc: toStrOrNull(form.current_ctc), expected_ctc: toStrOrNull(form.expected_ctc),
        work_authorization: toStrOrNull(form.work_authorization), linkedin_url: toStrOrNull(form.linkedin_url),
        job_locations: splitPlaces(form.job_locations).length ? splitPlaces(form.job_locations) : null,
        version: cand.version,
      });
      setCand(saved);
      setForm(toForm(saved));
      setMsg({ kind: "good", text: "Profile saved." });
    } catch (err) {
      setErrors(fieldErrors(err));
      setMsg({ kind: "bad", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
    <div className="row" style={{ marginBottom: 12 }}><span className="badge">{cand.completeness}% complete</span></div>
    <DocumentLibrary onFill={fillFrom} />
    <form onSubmit={save} noValidate>
      <div ref={formTop} style={{ scrollMarginTop: 16 }} />
      {msg ? <div style={{ marginBottom: 16 }}><Notice kind={msg.kind}>{msg.text}</Notice></div> : null}
      <section className="card">
        <div className="card-head"><h2>About you</h2></div>
        <div className="grid-2">
          <Field label="Headline" htmlFor="headline" error={errors.headline} className="span-all">
            <input id="headline" className="input" value={form.headline} onChange={(e) => set("headline", e.target.value)} placeholder="Engineering leader, cloud SaaS and payments" />
          </Field>
          <Field label="Summary" htmlFor="summary" error={errors.summary} className="span-all">
            <textarea id="summary" className="textarea" value={form.summary} onChange={(e) => set("summary", e.target.value)} />
          </Field>
          <Field label="Current location" htmlFor="loc" error={errors.current_location}>
            <input id="loc" className="input" value={form.current_location} onChange={(e) => set("current_location", e.target.value)} placeholder="Bengaluru" />
          </Field>
          <Field label="Where you want to work" htmlFor="job-locations" error={errors.job_locations}
            hint="Cities, or Remote, separated by commas. New Skill Match profiles start with these, and job search looks there.">
            <input id="job-locations" className="input" value={form.job_locations} onChange={(e) => set("job_locations", e.target.value)} placeholder="Bengaluru, Remote" />
          </Field>
          <Field label="Years of experience" htmlFor="yrs" error={errors.years_experience}>
            <input id="yrs" className="input num" type="number" min={0} max={60} value={form.years_experience} onChange={(e) => set("years_experience", e.target.value)} />
          </Field>
          <Field label="LinkedIn profile URL" htmlFor="li" error={errors.linkedin_url} className="span-all">
            <input id="li" className="input" value={form.linkedin_url} onChange={(e) => set("linkedin_url", e.target.value)} placeholder="https://www.linkedin.com/in/your-name" />
          </Field>
        </div>
      </section>
      <section className="card">
        <div className="card-head"><h2>Domains</h2><span className="subtle">Press Enter or comma to add</span></div>
        <div className="stack">
          <p className="hint" style={{ marginTop: -6 }}>Skills are on the Skill Match Profile tab, one list per resume.</p>
          <Field label="Industries you've worked in" htmlFor="domains" error={errors.domains}
            hint="A job in one of these scores higher on Industry/domain.">
            <ChipsInput id="domains" value={form.domains} onChange={(v) => set("domains", v)} placeholder="fintech, payments…" />
          </Field>
        </div>
      </section>
      <section className="card">
        <div className="card-head"><h2>Logistics</h2><span className="subtle">Pre-fills common application questions</span></div>
        <div className="grid-2">
          <Field label="Notice period (days)" htmlFor="notice" error={errors.notice_days}>
            <input id="notice" className="input num" type="number" min={0} max={365} value={form.notice_days} onChange={(e) => set("notice_days", e.target.value)} />
          </Field>
          <Field label="Work authorisation" htmlFor="auth" error={errors.work_authorization}>
            <input id="auth" className="input" value={form.work_authorization} onChange={(e) => set("work_authorization", e.target.value)} placeholder="Indian citizen" />
          </Field>
          <Field label="Current CTC" htmlFor="cctc" error={errors.current_ctc}>
            <input id="cctc" className="input" value={form.current_ctc} onChange={(e) => set("current_ctc", e.target.value)} placeholder="e.g. 85 LPA" />
          </Field>
          <Field label="Expected CTC" htmlFor="ectc" error={errors.expected_ctc}>
            <input id="ectc" className="input" value={form.expected_ctc} onChange={(e) => set("expected_ctc", e.target.value)} placeholder="e.g. 1.1 Cr" />
          </Field>
        </div>
      </section>
      <div className="sticky-actions">
        <button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Save profile"}</button>
      </div>
    </form>
    </>
  );
}
