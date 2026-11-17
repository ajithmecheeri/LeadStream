"use client";
import type { Answer } from "@fitfirst/api";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { AnswerRow } from "@/components/AnswerRow";
import { errorMessage, Field, fieldErrors, Notice } from "@/components/ui";
import { api } from "@/lib/api";

/** The answer bank (Profile → Answer bank, user 2026-11-16): answers to the screening questions application forms
 *  ask. The Apply kit and the browser extension fill a form's question from the answer whose question matches it
 *  or is worded alike. */
export function AnswerBank() {
  const [items, setItems] = useState<Answer[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ question: "", answer: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      setItems((await api.answers()).items);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    setErrors({});
    try {
      await api.addAnswer(form.question, form.answer);
      setForm({ question: "", answer: "" });
      setAdding(false);
      await load();
    } catch (err) {
      setErrors({ ...fieldErrors(err), _: errorMessage(err) });
    }
  }

  return (
    <div className="stack" style={{ gap: 16 }} data-testid="answer-bank">
      <div className="row">
        <p className="muted" style={{ margin: 0 }}>
          Answers to the screening questions application forms ask. Answer once: the Apply kit on every job and the
          browser extension fill a form&apos;s question from the answer whose question is the same or worded alike.
        </p>
        <span className="spacer" />
        <button type="button" className="btn btn-sm" onClick={() => setAdding((a) => !a)}>Add a question</button>
      </div>
      {error ? <Notice kind="bad">{error}</Notice> : null}
      {adding ? (
        <section className="card">
          <form className="stack" onSubmit={add} noValidate>
            {errors._ ? <Notice kind="bad">{errors._}</Notice> : null}
            <Field label="Question" htmlFor="q" error={errors.question}>
              <input id="q" className="input" value={form.question} placeholder="Do you have a valid passport?"
                onChange={(e) => setForm((f) => ({ ...f, question: e.target.value }))} />
            </Field>
            <Field label="Answer" htmlFor="a" error={errors.answer}>
              <textarea id="a" className="textarea" rows={3} value={form.answer} onChange={(e) => setForm((f) => ({ ...f, answer: e.target.value }))} />
            </Field>
            <div className="row">
              <button className="btn btn-primary btn-sm" disabled={!form.question.trim() || !form.answer.trim()}>Save question</button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAdding(false)}>Cancel</button>
            </div>
          </form>
        </section>
      ) : null}
      <section className="card">
        {items === null ? <div className="loading">Loading…</div> : (
          <ul className="blockers">
            {items.map((a) => <AnswerRow key={`${a.key}-${a.version ?? 0}-${a.answer ?? ""}`} a={a} onSaved={load} />)}
          </ul>
        )}
      </section>
    </div>
  );
}
