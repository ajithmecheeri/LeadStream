"use client";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { errorMessage, Field, fieldErrors, Notice, PasswordInput } from "@/components/ui";
import { api } from "@/lib/api";
import { splitPlaces } from "@/lib/places";
import { useSession } from "@/lib/session";

export default function SignUp() {
  const { signUp } = useSession();
  const [first, setFirst] = useState("");
  const [middle, setMiddle] = useState("");
  const [last, setLast] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [whatsapp, setWhatsapp] = useState("");
  const [places, setPlaces] = useState("");
  const [accept, setAccept] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  // An invite's link (user, 2026-11-17): the email is the invite's, and its role and free months apply at once.
  const [invite, setInvite] = useState<{ token: string; email: string; months: number } | null>(null);

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("invite");
    if (!token) return;
    api.viewInvite(token)
      .then((v) => {
        setInvite({ token, email: v.email, months: v.free_months });
        setEmail(v.email);
      })
      .catch((e) => setError(errorMessage(e)));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setErrors({});
    if (password !== confirm) {
      setErrors({ password_confirm: "The passwords don't match" });
      return;
    }
    setBusy(true);
    try {
      await signUp({
        first_name: first, middle_name: middle.trim() || null, last_name: last,
        email, password, password_confirm: confirm, accept_terms: accept,
        whatsapp_number: whatsapp.trim() || null,
        job_locations: splitPlaces(places),
        invite: invite?.token ?? null,
      });
    } catch (err) {
      setErrors(fieldErrors(err));
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack" onSubmit={submit} noValidate>
      <div>
        <h1>Create your account</h1>
        <p className="muted">BrewMyJob scores the jobs in your alert emails against your profile. You always do the applying.</p>
      </div>
      {error ? <Notice kind="bad">{error}</Notice> : null}
      {invite ? (
        <Notice kind="good">
          You&apos;re invited{invite.months ? `: ${invite.months} month${invite.months === 1 ? "" : "s"} free` : ""}.
        </Notice>
      ) : null}
      <div className="name-row">
        <Field label="First name" htmlFor="first-name" error={errors.first_name}>
          <input id="first-name" className="input" autoComplete="given-name" value={first} onChange={(e) => setFirst(e.target.value)} />
        </Field>
        <Field label="Middle name" htmlFor="middle-name" error={errors.middle_name} hint="Optional">
          <input id="middle-name" className="input" autoComplete="additional-name" value={middle} onChange={(e) => setMiddle(e.target.value)} />
        </Field>
        <Field label="Last name" htmlFor="last-name" error={errors.last_name}>
          <input id="last-name" className="input" autoComplete="family-name" value={last} onChange={(e) => setLast(e.target.value)} />
        </Field>
      </div>
      <Field label="Email" htmlFor="email" error={errors.email}>
        <input id="email" className="input" type="email" autoComplete="email" value={email} readOnly={invite !== null}
          onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Field label="Password" htmlFor="password" error={errors.password} hint="At least 10 characters.">
        <PasswordInput id="password" autoComplete="new-password" value={password} onChange={setPassword} />
      </Field>
      <Field label="Re-enter password" htmlFor="password-confirm" error={errors.password_confirm}
        hint={confirm && confirm === password ? "Passwords match." : undefined}>
        <PasswordInput id="password-confirm" autoComplete="new-password" value={confirm}
          onChange={(v) => { setConfirm(v); setErrors(({ password_confirm: _, ...rest }) => rest); }} />
      </Field>
      <Field label="Where do you want to work?" htmlFor="job-locations" error={errors.job_locations}
        hint="Cities, or Remote, separated by commas. We look for jobs there; you can change it later on your Profile.">
        <input id="job-locations" className="input" placeholder="Bengaluru, Remote"
          value={places} onChange={(e) => setPlaces(e.target.value)} />
      </Field>
      <Field label="WhatsApp number" htmlFor="whatsapp" error={errors.whatsapp_number}
        hint="Optional. For a WhatsApp message when a strong match arrives; you verify it with a code in Settings.">
        <input id="whatsapp" className="input num" type="tel" inputMode="tel" autoComplete="tel" placeholder="+91 98765 43210"
          value={whatsapp} onChange={(e) => setWhatsapp(e.target.value)} />
      </Field>
      <label className="check">
        <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
        <span className="muted">
          I agree that BrewMyJob may use my profile, resumes and job alerts to match jobs, draft documents and notify me.
          It never stores my LinkedIn, Naukri or email passwords.
        </span>
      </label>
      {errors.accept_terms ? <span className="field-error">{errors.accept_terms}</span> : null}
      <button className="btn btn-primary" disabled={busy || !first.trim() || !last.trim() || !email || !password || !confirm || !accept || !splitPlaces(places).length}>{busy ? "Creating…" : "Create account"}</button>
      <p className="subtle">Already have an account? <Link href="/sign-in">Sign in</Link></p>
    </form>
  );
}
