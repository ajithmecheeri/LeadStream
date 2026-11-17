"use client";
import type { GoogleSearches } from "@fitfirst/api";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { GoogleAlerts, GoogleRoles } from "@/components/GoogleAlerts";
import { errorMessage, Field, fieldErrors, Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { googleUrl, guessFromLink, WINDOWS, type Window } from "@/lib/found";

const EMPTY = { url: "", title: "", company: "", location: "", description: "" };

/** Route 1 (2026-11-14): Google searches you run in your own browser, and a form to add what you find. */
export default function FindJobsPage() {
  const router = useRouter();
  const { me } = useSession();
  const [data, setData] = useState<GoogleSearches | null>(null);
  const [period, setPeriod] = useState<Window>("day");
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Bumped when the roles on top change: the searches and the alerts follow them (user, 2026-11-17).
  const [version, setVersion] = useState(0);

  useEffect(() => {
    api.googleSearches().then(setData, (e) => setError(errorMessage(e)));
  }, [version]);

  function setLink(url: string) {
    const guess = guessFromLink(url);
    setForm((f) => ({
      ...f,
      url,
      title: f.title || guess?.title || "",
      company: f.company || guess?.company || "",
    }));
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErrors({});
    setError(null);
    try {
      const job = await api.addFoundJob({
        url: form.url,
        title: form.title,
        company: form.company,
        location: form.location.trim() || null,
        description: form.description.trim() || null,
      });
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      setErrors(fieldErrors(err));
      setError(errorMessage(err));
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Find jobs on Google"
        sub="Google searches for LinkedIn, Naukri and Foundit jobs, from the roles below and your job locations. Run them in your own browser and add the jobs you like, or let Google Alerts bring them; BrewMyJob never opens these sites itself."
        actions={<Link className="btn btn-sm" href="/jobs">Back to Jobs</Link>}
      />

      <GoogleRoles onSaved={() => setVersion((v) => v + 1)} />

      <div style={{ margin: "16px 0" }}>
        <Notice kind="info">
          Rather not search by hand? Set up <a href="#google-alerts">Google Alerts</a> once, below: Google watches for new
          jobs and BrewMyJob adds them for you, three times a day.
        </Notice>
      </div>

      <section className="card stack" aria-label="Google searches">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>Searches</h2>
          <select className="select narrow" aria-label="Posted" value={period} onChange={(e) => setPeriod(e.target.value as Window)}>
            {WINDOWS.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}
          </select>
        </div>
        {!data && !error ? (
          <div className="loading">Loading…</div>
        ) : data && data.searches.length === 0 ? (
          <p className="muted">
            Add roles above (or target roles to your Skill Match Profile) to get searches here. <Link href="/profile">Open Profile</Link>
          </p>
        ) : data ? (
          <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {data.searches.map((s) => (
              <li key={`${s.role}|${s.place ?? ""}`} className="row" style={{ justifyContent: "space-between" }} data-testid="google-search">
                <span>
                  <strong>{s.role}</strong>
                  {s.place ? <span className="muted"> · {s.place}</span> : null}
                </span>
                <span className="row">
                  {data.portals.map((p) => (
                    <a key={p.id} className="btn btn-sm" href={googleUrl(s.queries[p.id] ?? "", period)} target="_blank"
                      rel="noopener noreferrer" aria-label={`Search ${p.label} for ${s.role}${s.place ? ` in ${s.place}` : ""} on Google`}>
                      {p.label} ↗
                    </a>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        <p className="subtle">
          Google shows only pages it has already found, usually hours to a day after a job is posted. Your alert emails stay the quickest way to hear of new LinkedIn and Naukri jobs.
        </p>
      </section>

      <form className="card stack" style={{ marginTop: 16 }} onSubmit={add} noValidate aria-label="Add a job you found">
        <h2>Add a job you found</h2>
        <Field label="Link to the job" htmlFor="found-url" error={errors.url} hint="The job's page on LinkedIn, Naukri or Foundit">
          <input id="found-url" className="input" type="url" placeholder="https://www.linkedin.com/jobs/view/…" value={form.url}
            onChange={(e) => setLink(e.target.value)} />
        </Field>
        <div className="grid-2">
          <Field label="Job title" htmlFor="found-title" error={errors.title}>
            <input id="found-title" className="input" value={form.title} onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, title: v })); }} />
          </Field>
          <Field label="Company" htmlFor="found-company" error={errors.company}>
            <input id="found-company" className="input" value={form.company} onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, company: v })); }} />
          </Field>
        </div>
        <Field label="Location (optional)" htmlFor="found-location" error={errors.location} hint="As the job shows it, e.g. Bengaluru (Hybrid)">
          <input id="found-location" className="input" value={form.location} onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, location: v })); }} />
        </Field>
        <Field label="Job description (optional)" htmlFor="found-description" error={errors.description}
          hint="Copy the description from the job's page and paste it here for a full match score. Without it, the job is scored on its title only.">
          <textarea id="found-description" className="textarea" rows={6} value={form.description}
            onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, description: v })); }} />
        </Field>
        {error ? <Notice kind="bad">{error}</Notice> : null}
        <div className="row">
          <button className="btn btn-primary" type="submit" disabled={saving}>{saving ? "Adding…" : "Add job"}</button>
        </div>
      </form>
      {/* Google Alerts moved here from Job sources, which is for admins now (user, 2026-11-17). */}
      <div style={{ marginTop: 16 }}>
        <GoogleAlerts timeZone={me?.timezone ?? "Asia/Kolkata"} version={version} />
      </div>
    </>
  );
}
