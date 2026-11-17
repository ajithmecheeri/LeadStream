"use client";
import type { AdminSettings } from "@fitfirst/api";
import { useEffect, useState, type FormEvent } from "react";
import { InvitesCard } from "@/components/InvitesCard";
import { errorMessage, Field, fieldErrors, Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

/** Super admin only: values that apply to every user. The API refuses everyone else. */
export default function AdminSettingsPage() {
  const { me } = useSession();
  const [current, setCurrent] = useState<AdminSettings | null>(null);
  const [form, setForm] = useState({ warn: "", auto: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (me?.role !== "super_admin") return;
    api
      .adminSettings()
      .then((s) => {
        setCurrent(s);
        setForm({ warn: String(s.job_expiry_warn_days), auto: String(s.job_expiry_auto_days) });
      })
      .catch((e) => setError(errorMessage(e)));
  }, [me?.role]);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrors({});
    setError(null);
    setSaved(false);
    try {
      const s = await api.saveAdminSettings({ job_expiry_warn_days: Number(form.warn), job_expiry_auto_days: Number(form.auto) });
      setCurrent(s);
      setSaved(true);
    } catch (err) {
      const f = fieldErrors(err);
      setErrors(f);
      // A rule across both fields (auto before warn) has no single field.
      if (f[""]) setError(f[""].replace(/^Value error, /, ""));
      else if (!f.job_expiry_warn_days && !f.job_expiry_auto_days) setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (me && me.role !== "super_admin") return <Notice kind="bad">This page is for the super admin.</Notice>;
  if (error && !current) return <Notice kind="bad">{error}</Notice>;
  if (!current) return <div className="loading">Loading…</div>;

  return (
    <>
      <PageHeader title="Admin settings" sub="These apply to every user. Changes take effect straight away and are logged." />
      <form className="card stack" onSubmit={save} noValidate>
        <div className="card-head"><h2>Old jobs</h2></div>
        <p className="muted">
          Alert emails don&apos;t say when a job closes, so BrewMyJob goes by how long it has been since an alert last showed the job (or since
          the user said it&apos;s still open). Jobs a user has applied to never expire.
        </p>
        <div className="grid-2">
          <Field label="Show “May have expired” after (days)" htmlFor="warn" error={errors.job_expiry_warn_days}
            hint="The job gets an amber warning and a to-do: check the posting.">
            <input id="warn" className="input num" type="number" min={1} max={365} value={form.warn}
              onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, warn: v })); }} />
          </Field>
          <Field label="Move to Expired after (days)" htmlFor="auto" error={errors.job_expiry_auto_days}
            hint="Checked once a day. At least as many days as the warning.">
            <input id="auto" className="input num" type="number" min={1} max={365} value={form.auto}
              onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, auto: v })); }} />
          </Field>
        </div>
        {error ? <Notice kind="bad">{error}</Notice> : null}
        {saved ? <Notice kind="good">Saved.</Notice> : null}
        <div className="row">
          <button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
          {current.updated_at ? <span className="subtle">Last changed {new Date(current.updated_at).toLocaleString("en-IN")}</span> : null}
        </div>
      </form>
      <InvitesCard />
    </>
  );
}
