"use client";
import type { ApplyKit as Kit } from "@fitfirst/api";
import Link from "next/link";
import { useState } from "react";
import { errorMessage, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { downloadBlob } from "@/lib/documents";

/** Milestone 14.2: everything a job's application form is likely to ask, in Workday's order, each with Copy, and the
 * suggested resume and cover letter. Works on any site, including LinkedIn and Naukri: nothing is filled for you. */
export function ApplyKit({ jobId }: { jobId: string }) {
  const [kit, setKit] = useState<Kit | null>(null);
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !kit) {
      try {
        setKit(await api.applyKit(jobId));
      } catch (e) {
        setError(errorMessage(e));
      }
    }
  }

  async function copy(key: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(key);
      setTimeout(() => setCopied((c) => (c === key ? null : c)), 1500);
    } catch {
      setError("Your browser didn't allow copying. Select the text and copy it instead.");
    }
  }

  async function download(id: string, label: string, kind: "resume" | "cover_letter") {
    try {
      downloadBlob(kind === "resume" ? await api.resumeFile(id) : await api.coverLetterFile(id), label);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <section className="card stack" style={{ marginBottom: 16 }} data-testid="apply-kit">
      <div className="card-head">
        <h2>Apply kit</h2>
        <button type="button" className="btn btn-sm" onClick={() => void toggle()} aria-expanded={open}>{open ? "Hide" : "Show fields to copy"}</button>
      </div>
      {!open ? <p className="subtle" style={{ margin: 0 }}>Your answers for this job&apos;s application form, ready to copy, with the suggested resume.</p> : null}
      {open && error ? <Notice kind="bad">{error}</Notice> : null}
      {open && !kit && !error ? <p className="subtle">Loading…</p> : null}
      {open && kit ? (
        <>
          {kit.missing.length ? (
            <Notice kind="warn">
              Forms usually ask for {kit.missing.join(", ").toLowerCase()}. <Link href="/profile#apply">Add them on Profile</Link>.
            </Notice>
          ) : null}
          {kit.documents.length ? (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {kit.documents.map((d) => (
                <button key={d.id} type="button" className="btn btn-sm" onClick={() => void download(d.id, d.label, d.kind)}>
                  Download {d.kind === "resume" ? "resume" : "cover letter"}: {d.label}
                </button>
              ))}
            </div>
          ) : null}
          {kit.sections.map((s) => (
            <div key={s.title} className="kit-section">
              <h3>{s.title}</h3>
              {s.fields.map((f) => (
                <div key={f.key} className="kit-row" data-testid="kit-field">
                  <span className="kit-label subtle">{f.label}</span>
                  <span className="kit-value">{f.value}</span>
                  <button type="button" className="btn btn-sm btn-ghost" onClick={() => void copy(f.key, f.value)} aria-label={`Copy ${f.label}`}>
                    {copied === f.key ? "Copied" : "Copy"}
                  </button>
                </div>
              ))}
            </div>
          ))}
        </>
      ) : null}
    </section>
  );
}
