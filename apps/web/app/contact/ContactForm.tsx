"use client";
import { useState, type FormEvent } from "react";
import { errorMessage, fieldErrors } from "@/components/ui";
import { api } from "@/lib/api";
import s from "../_legal/legal.module.css";

type Topic = "general" | "support" | "privacy" | "feedback";
const TOPICS: { value: Topic; label: string }[] = [
  { value: "general", label: "A question" },
  { value: "support", label: "Help with my account" },
  { value: "privacy", label: "Privacy: see, correct or delete my data" },
  { value: "feedback", label: "Feedback or an idea" },
];

/** The contact form. The hidden "website" field catches form-filling bots; the answer is the same either way. */
export function ContactForm() {
  const [form, setForm] = useState({ name: "", email: "", topic: "general" as Topic, message: "", website: "" });
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function send(e: FormEvent) {
    e.preventDefault();
    setState("busy");
    setError(null);
    setErrors({});
    try {
      await api.contact({ ...form, name: form.name.trim(), email: form.email.trim(), message: form.message.trim() });
      setState("done");
    } catch (err) {
      setErrors(fieldErrors(err));
      setError(errorMessage(err));
      setState("idle");
    }
  }

  if (state === "done") {
    return <p className={s.ok} role="status" data-testid="contact-done">Thank you. Your message has reached the BrewMyJob team; we&apos;ll reply to {form.email}.</p>;
  }

  return (
    <form className={s.form} onSubmit={send} noValidate data-testid="contact-form">
      <label>
        Your name
        <input autoComplete="name" value={form.name} maxLength={100} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
        {errors.name ? <span className={s.bad}>{errors.name}</span> : null}
      </label>
      <label>
        Email address
        <input type="email" autoComplete="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
        {errors.email ? <span className={s.bad}>{errors.email}</span> : null}
      </label>
      <label>
        About
        <select value={form.topic} onChange={(e) => setForm((f) => ({ ...f, topic: e.target.value as Topic }))}>
          {TOPICS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
      </label>
      <label>
        Message
        <textarea value={form.message} maxLength={2000} onChange={(e) => setForm((f) => ({ ...f, message: e.target.value }))} />
        {errors.message ? <span className={s.bad}>{errors.message}</span> : null}
      </label>
      <div className={s.hidden} aria-hidden="true">
        <label>
          Website
          <input tabIndex={-1} autoComplete="off" value={form.website} onChange={(e) => setForm((f) => ({ ...f, website: e.target.value }))} />
        </label>
      </div>
      {error && !Object.keys(errors).length ? <p className={s.bad} role="alert">{error}</p> : null}
      <button className={s.button} disabled={state === "busy"}>{state === "busy" ? "Sending…" : "Send message"}</button>
    </form>
  );
}
