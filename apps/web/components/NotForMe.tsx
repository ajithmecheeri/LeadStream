"use client";
import type { NotForMeReason, UserJobDetail } from "@fitfirst/api";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { errorMessage, Notice } from "@/components/ui";
import { api } from "@/lib/api";

export const NOT_FOR_ME_REASONS: { value: NotForMeReason; label: string; hint?: string }[] = [
  { value: "field", label: "Not my field", hint: "Jobs in that field score lower" },
  { value: "too_junior", label: "Too junior", hint: "Lower levels score lower" },
  { value: "too_senior", label: "Too senior", hint: "Higher levels score lower" },
  { value: "location", label: "Location doesn't work", hint: "Jobs only in that city score lower" },
  { value: "company", label: "Not this company", hint: "Its jobs score lower" },
  { value: "salary", label: "Salary too low" },
  { value: "applied_elsewhere", label: "Already applied elsewhere" },
  { value: "other", label: "Something else" },
];

export function reasonLabel(value: string | null | undefined): string | null {
  return NOT_FOR_ME_REASONS.find((r) => r.value === value)?.label ?? null;
}

/** "Not for me" on a job (milestone 13 A): pick a reason; the job is ignored, and BrewMyJob learns from the reason. */
export function NotForMe({ job, onJob, onClose }: { job: UserJobDetail; onJob: (j: UserJobDetail) => void; onClose: () => void }) {
  const [reason, setReason] = useState<NotForMeReason | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!reason) return;
    setBusy(true);
    setError(null);
    try {
      onJob(await api.notForMe(job.id, { reason, note: note.trim() || null, version: job.version }));
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card stack" style={{ marginBottom: 16 }} onSubmit={submit} data-testid="not-for-me-form">
      <strong>Why isn&apos;t this job for you?</strong>
      <div className="stack" role="radiogroup" aria-label="Reason" style={{ gap: 6 }}>
        {NOT_FOR_ME_REASONS.map((r) => (
          <label key={r.value} style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
            <input type="radio" name="reason" value={r.value} checked={reason === r.value} onChange={() => setReason(r.value)} />
            <span>
              {r.label}
              {r.hint ? <span className="subtle"> · {r.hint}</span> : null}
            </span>
          </label>
        ))}
      </div>
      <input className="input" maxLength={500} placeholder="Anything to add (optional)" aria-label="Note" value={note} onChange={(e) => setNote(e.target.value)} />
      <p className="hint" style={{ margin: 0 }}>
        The job moves to Ignored. What BrewMyJob learns shows on your <Link href="/profile#learned">Profile</Link>, where you can remove it.
      </p>
      {error ? <Notice kind="bad">{error}</Notice> : null}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btn-primary" disabled={busy || !reason}>{busy ? "Saving…" : "Not for me"}</button>
        <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
      </div>
    </form>
  );
}
