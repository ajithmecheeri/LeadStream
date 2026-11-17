"use client";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { errorMessage, Field, Notice, PasswordInput } from "@/components/ui";
import { useSession } from "@/lib/session";

export default function SignIn() {
  const { signIn } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack" onSubmit={submit} noValidate>
      <div>
        <h1>Sign in</h1>
        <p className="muted">Pick up where you left off.</p>
      </div>
      {error ? <Notice kind="bad">{error}</Notice> : null}
      <Field label="Email" htmlFor="email">
        <input id="email" className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Field label="Password" htmlFor="password">
        <PasswordInput id="password" autoComplete="current-password" value={password} onChange={setPassword} />
      </Field>
      <button className="btn btn-primary" disabled={busy || !email || !password}>{busy ? "Signing in…" : "Sign in"}</button>
      <p className="subtle">New here? <Link href="/sign-up">Create an account</Link></p>
    </form>
  );
}
