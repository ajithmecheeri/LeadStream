"use client";
import { useState, type FormEvent } from "react";
import { errorMessage } from "@/components/ui";
import { api } from "@/lib/api";
import s from "./home.module.css";

/** The home page's waitlist form. The hidden "website" field catches form-filling bots. */
export function WaitlistForm() {
  const [email, setEmail] = useState("");
  const [website, setWebsite] = useState("");
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [error, setError] = useState<string | null>(null);

  async function join(e: FormEvent) {
    e.preventDefault();
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setError("Enter your email address, like you@example.com.");
      return;
    }
    setState("busy");
    setError(null);
    try {
      await api.joinWaitlist({ email: email.trim(), source: "home", website });
      setState("done");
    } catch (err) {
      setError(errorMessage(err));
      setState("idle");
    }
  }

  if (state === "done") {
    return (
      <p className={s.formDone} role="status" data-testid="waitlist-done">
        You&apos;re on the list. We&apos;ll email your forwarding address when your spot opens.
      </p>
    );
  }

  return (
    <form className={s.form} onSubmit={join} noValidate>
      <label htmlFor="wl-email" className={s.srOnly}>Email address</label>
      <input id="wl-email" className={s.input} type="email" placeholder="you@example.com" autoComplete="email" value={email}
        onChange={(e) => setEmail(e.target.value)} aria-invalid={error ? true : undefined} aria-describedby={error ? "wl-error" : undefined} />
      <div className={s.honeypot} aria-hidden="true">
        <label htmlFor="wl-website">Website</label>
        <input id="wl-website" tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
      </div>
      <button type="submit" className={`${s.btnDark} ${s.formBtn}`} disabled={state === "busy"}>
        {state === "busy" ? "Joining…" : "Join the waitlist"}
      </button>
      {error ? <p id="wl-error" className={s.formError} role="alert" style={{ flexBasis: "100%" }}>{error}</p> : null}
      <p className={s.formNote} style={{ flexBasis: "100%" }}>We only use your email to tell you when your spot opens.</p>
    </form>
  );
}
