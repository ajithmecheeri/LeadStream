"use client";
import type { Invite, InviteMade } from "@fitfirst/api";
import { useEffect, useState, type FormEvent } from "react";
import { errorMessage, Field, fieldErrors, Notice } from "@/components/ui";
import { api } from "@/lib/api";

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="btn btn-sm" onClick={() => navigator.clipboard.writeText(text).then(() => setDone(true), () => setDone(false))}>
      {done ? "Copied" : label}
    </button>
  );
}

const STATE: Record<Invite["state"], { label: string; kind: string }> = {
  open: { label: "Waiting", kind: "badge-info" },
  accepted: { label: "Accepted", kind: "badge-good" },
  revoked: { label: "Withdrawn", kind: "" },
  expired: { label: "Expired", kind: "" },
};

/** The super admin's invites (user, 2026-11-17): a job seeker, with a 1- or 3-month coupon or none, or an admin.
 *  No email is sent yet (no email provider): the link is shown once, to copy and send. */
export function InvitesCard() {
  const [list, setList] = useState<Invite[] | null>(null);
  const [form, setForm] = useState({ email: "", role: "job_seeker" as "job_seeker" | "admin", months: "1" });
  const [made, setMade] = useState<InviteMade | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.invites().then(setList).catch((e) => setError(errorMessage(e)));
  useEffect(() => {
    void load();
  }, []);

  async function make(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrors({});
    setError(null);
    setMade(null);
    try {
      const m = await api.makeInvite({
        email: form.email.trim(),
        role: form.role,
        free_months: form.role === "admin" ? 0 : (Number(form.months) as 0 | 1 | 3),
      });
      setMade(m);
      setForm((f) => ({ ...f, email: "" }));
      await load();
    } catch (err) {
      setErrors(fieldErrors(err));
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    try {
      await api.revokeInvite(id);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <section className="card stack" style={{ marginTop: 16 }} data-testid="invites">
      <div className="card-head">
        <h2>Invites</h2>
        <span className="subtle">Job seekers with a free coupon, or admins</span>
      </div>
      <p className="muted">
        A job seeker&apos;s coupon gives 1 or 3 months free, from the day they accept. An admin manages Job sources and
        never needs a plan. Each link works once, for that email only, for 14 days. Emails aren&apos;t sent yet: copy the
        link and send it yourself.
      </p>
      <form className="row" style={{ alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={make} noValidate>
        <Field label="Email" htmlFor="invite-email" error={errors.email}>
          <input id="invite-email" className="input" type="email" value={form.email}
            onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, email: v })); }} />
        </Field>
        <Field label="Role" htmlFor="invite-role">
          <select id="invite-role" className="select" value={form.role}
            onChange={(e) => { const v = e.target.value as "job_seeker" | "admin"; setForm((f) => ({ ...f, role: v })); }}>
            <option value="job_seeker">Job seeker</option>
            <option value="admin">Admin</option>
          </select>
        </Field>
        {form.role === "job_seeker" ? (
          <Field label="Coupon" htmlFor="invite-months" error={errors.free_months}>
            <select id="invite-months" className="select" value={form.months}
              onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, months: v })); }}>
              <option value="1">1 month free</option>
              <option value="3">3 months free</option>
              <option value="0">No coupon (pays)</option>
            </select>
          </Field>
        ) : null}
        <button className="btn btn-primary" disabled={busy || !form.email.trim()}>{busy ? "Making…" : "Make invite"}</button>
      </form>
      {error ? <Notice kind="bad">{error}</Notice> : null}
      {made ? (
        <Notice kind="good">
          <span data-testid="invite-link">Invite for {made.email}: <code>{made.link}</code></span>{" "}
          <CopyButton text={made.link} label="Copy link" />
          <br />
          This link is shown once. Send it to {made.email}.
        </Notice>
      ) : null}
      {list && list.length > 0 ? (
        <table className="table">
          <thead><tr><th>Email</th><th>Role</th><th>Coupon</th><th>State</th><th>Made</th><th /></tr></thead>
          <tbody>
            {list.map((i) => (
              <tr key={i.id} data-testid="invite-row">
                <td>{i.email}</td>
                <td>{i.role === "admin" ? "Admin" : "Job seeker"}</td>
                <td>{i.free_months ? `${i.free_months} month${i.free_months === 1 ? "" : "s"}` : "–"}</td>
                <td><span className={`badge ${STATE[i.state].kind}`}>{STATE[i.state].label}</span></td>
                <td className="subtle">{new Date(i.created_at).toLocaleDateString("en-IN")}</td>
                <td>{i.state === "open" ? <button type="button" className="btn btn-ghost btn-sm" onClick={() => revoke(i.id)}>Withdraw</button> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : list ? <p className="muted">No invites yet.</p> : null}
    </section>
  );
}
