"use client";
import { ApiError } from "@fitfirst/api";
import { useState, type KeyboardEvent, type ReactNode } from "react";

export function Field(props: { label: string; htmlFor?: string; error?: string; hint?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <div className={`field ${props.error ? "has-error" : ""} ${props.className ?? ""}`}>
      <label htmlFor={props.htmlFor}>{props.label}</label>
      {props.children}
      {props.error ? <span className="field-error" role="alert">{props.error}</span> : props.hint ? <span className="hint">{props.hint}</span> : null}
    </div>
  );
}

export function Notice({ kind = "info", children }: { kind?: "info" | "good" | "warn" | "bad"; children: ReactNode }) {
  return <div className={`notice notice-${kind}`} role={kind === "bad" ? "alert" : "status"}>{children}</div>;
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {sub ? <p className="muted">{sub}</p> : null}
      </div>
      {actions ? <div className="row">{actions}</div> : null}
    </div>
  );
}

/** A password field with a Show/Hide button. The button is outside the tab order's way: Tab goes field → button. */
export function PasswordInput(props: { id: string; value: string; onChange: (v: string) => void; autoComplete: string }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="password">
      <input id={props.id} className="input" type={shown ? "text" : "password"} autoComplete={props.autoComplete}
        value={props.value} onChange={(e) => props.onChange(e.target.value)} spellCheck={false} autoCapitalize="off" />
      <button type="button" className="btn btn-ghost btn-sm" aria-controls={props.id} aria-pressed={shown}
        aria-label={shown ? "Hide password" : "Show password"} onClick={() => setShown((s) => !s)}>
        {shown ? "Hide" : "Show"}
      </button>
    </div>
  );
}

/** Free-text list input: Enter or comma adds, Backspace on empty removes the last chip. */
export function ChipsInput({ id, value, onChange, placeholder }: { id?: string; value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const [draft, setDraft] = useState("");
  const add = (raw: string) => {
    const parts = raw.split(",").map((s) => s.trim()).filter(Boolean);
    const next = [...value];
    for (const p of parts) if (!next.some((x) => x.toLowerCase() === p.toLowerCase())) next.push(p);
    onChange(next);
    setDraft("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      if (draft.trim()) add(draft);
    } else if (e.key === "Backspace" && !draft && value.length) {
      onChange(value.slice(0, -1));
    }
  };
  return (
    <div className="chips">
      {value.map((v) => (
        <span className="chip" key={v}>
          {v}
          <button type="button" aria-label={`Remove ${v}`} onClick={() => onChange(value.filter((x) => x !== v))}>×</button>
        </span>
      ))}
      <input id={id} value={draft} placeholder={value.length ? "" : placeholder} onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey} onBlur={() => draft.trim() && add(draft)} />
    </div>
  );
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return "Something went wrong. Check your connection and try again.";
}

export function fieldErrors(e: unknown): Record<string, string> {
  return e instanceof ApiError ? e.fieldErrors() : {};
}

export const toNumOrNull = (s: string): number | null => (s.trim() === "" ? null : Number(s));
export const toStrOrNull = (s: string): string | null => (s.trim() === "" ? null : s.trim());
