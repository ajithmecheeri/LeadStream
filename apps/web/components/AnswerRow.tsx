"use client";
import type { Answer } from "@fitfirst/api";
import { useState, type FormEvent } from "react";
import { errorMessage, fieldErrors } from "@/components/ui";
import { api } from "@/lib/api";

/** One answer-bank question (Profile → Answer bank, and Profile → Application Autofill Information). Questions
 * with usual answers (Yes / No…) are answered with one click; any other answer can still be typed. */
export function AnswerRow({ a, onSaved }: { a: Answer; onSaved: () => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(a.answer ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.saveAnswer(a.key, text, a.source === "you" ? a.version : null);
      setEditing(false);
      await onSaved();
    } catch (err) {
      setError(fieldErrors(err).answer ?? errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  /** A quick pick (Yes / No…): saved at once. */
  async function pick(choice: string) {
    if (choice === a.answer) return;
    setBusy(true);
    setError(null);
    try {
      await api.saveAnswer(a.key, choice, a.source === "you" ? a.version : null);
      setText(choice);
      await onSaved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    const what = a.standard ? "Clear your saved answer? Your profile's answer (if any) applies again." : "Delete this question?";
    if (!window.confirm(what)) return;
    try {
      await api.deleteAnswer(a.key);
      await onSaved();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <li data-testid="answer-row">
      <div className="row">
        <strong>{a.question}</strong>
        {a.required ? <span className="badge">Asked often</span> : null}
        {a.stale ? <span className="badge badge-warn">Saved over 30 days ago: still right?</span> : null}
      </div>
      {(a.choices ?? []).length && !editing ? (
        <div className="row" role="group" aria-label={`Answer: ${a.question}`}>
          {(a.choices ?? []).map((c) => (
            <button
              key={c}
              type="button"
              className={`btn btn-sm${a.answer === c ? " btn-primary" : ""}`}
              aria-pressed={a.answer === c}
              disabled={busy}
              onClick={() => void pick(c)}
            >
              {c}
            </button>
          ))}
          {a.answer && !(a.choices ?? []).includes(a.answer) ? <span data-testid="answer-text">{a.answer}</span> : null}
          <button className="btn btn-sm btn-ghost" onClick={() => setEditing(true)}>Other answer</button>
          {a.source === "you" ? <button className="btn btn-sm btn-ghost danger" onClick={remove}>Clear</button> : null}
        </div>
      ) : editing ? (
        <form className="stack" onSubmit={save}>
          <textarea className="textarea" rows={3} aria-label={`Answer: ${a.question}`} value={text} onChange={(e) => setText(e.target.value)} />
          <div className="row">
            <button className="btn btn-sm btn-primary" disabled={busy || !text.trim()}>Save</button>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => { setEditing(false); setText(a.answer ?? ""); }}>Cancel</button>
          </div>
        </form>
      ) : (
        <div className="row">
          <span className={a.answer ? "" : "muted"} data-testid="answer-text">{a.answer ?? "Not answered yet"}</span>
          {a.source === "profile" ? <span className="subtle">from your profile</span> : null}
          <button className="btn btn-sm btn-ghost" onClick={() => setEditing(true)} aria-label={`${a.answer ? "Edit" : "Answer"}: ${a.question}`}>
            {a.answer ? "Edit" : "Answer"}
          </button>
          {a.source === "you" ? <button className="btn btn-sm btn-ghost danger" onClick={remove}>{a.standard ? "Clear" : "Delete"}</button> : null}
        </div>
      )}
      {error ? <span className="field-error">{error}</span> : null}
    </li>
  );
}
