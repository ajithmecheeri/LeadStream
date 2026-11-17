"use client";
import type { CandidateDraft, CoverLetter, Resume } from "@fitfirst/api";
import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import { errorMessage, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { ACCEPT, downloadBlob, sizeLabel, uploadProblem } from "@/lib/documents";
import { toBase64 } from "@/lib/jobs";

type Kind = "resume" | "letter";
type Doc = (Resume | CoverLetter) & { is_main: boolean };

const COPY = {
  resume: {
    title: "Resumes", main: "Primary", makeMain: "Make primary", noun: "resume", testid: "resume",
    hint: (n: number, max: number) => `${n} of ${max}: one primary and up to ${max - 1} variations. Each has its own Skill Match profile; the primary resume's match % shows on every job.`,
  },
  letter: {
    title: "Cover letters", main: "Default", makeMain: "Make default", noun: "cover letter", testid: "letter",
    hint: (n: number, max: number) => `${n} of ${max}. The best fit for each job is suggested on the job's page.`,
  },
} as const;

const asDocs = (kind: Kind, items: (Resume | CoverLetter)[]): Doc[] =>
  items.map((d) => ({ ...d, is_main: kind === "resume" ? (d as Resume).is_primary : (d as CoverLetter).is_default }));

function Library({ kind, onFill }: { kind: Kind; onFill?: (draft: CandidateDraft, label: string) => void }) {
  const c = COPY[kind];
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [limit, setLimit] = useState(kind === "resume" ? 4 : 5);
  const [msg, setMsg] = useState<{ kind: "good" | "bad"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [pasting, setPasting] = useState(false);
  const [paste, setPaste] = useState({ label: "", text: "" });
  const [renaming, setRenaming] = useState<{ id: string; label: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const replaceInput = useRef<HTMLInputElement>(null);
  const [replacing, setReplacing] = useState<Doc | null>(null);

  const load = useCallback(async () => {
    try {
      const list = kind === "resume" ? await api.resumes() : await api.coverLetters();
      setDocs(asDocs(kind, list.items));
      setLimit(list.limit);
    } catch (e) {
      setMsg({ kind: "bad", text: errorMessage(e) });
    }
  }, [kind]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(id: string, fn: () => Promise<unknown>, done?: string) {
    setBusy(id);
    setMsg(null);
    try {
      await fn();
      await load();
      if (done) setMsg({ kind: "good", text: done });
    } catch (e) {
      setMsg({ kind: "bad", text: errorMessage(e) });
    } finally {
      setBusy(null);
    }
  }

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!files.length) return;
    const problems: string[] = [];
    let added = 0;
    setBusy("upload");
    setMsg(null);
    for (const f of files) {
      const problem = uploadProblem(f);
      if (problem) {
        problems.push(problem);
        continue;
      }
      try {
        const body = { file_name: f.name, content_base64: toBase64(new Uint8Array(await f.arrayBuffer())) };
        if (kind === "resume") await api.addResume(body);
        else await api.addCoverLetter(body);
        added += 1;
      } catch (err) {
        problems.push(`${f.name}: ${errorMessage(err)}`);
      }
    }
    await load();
    setBusy(null);
    setMsg(
      problems.length
        ? { kind: "bad", text: problems.join(" ") }
        : { kind: "good", text: `${added} ${c.noun}${added === 1 ? "" : "s"} added. Your jobs are being scored again.` },
    );
  }

  /** A new version of a resume (2026-11-13): it keeps its name and Skill Match profile; the profile's skills are
   *  read again from it. */
  async function replace(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    const d = replacing;
    setReplacing(null);
    if (!f || !d) return;
    const problem = uploadProblem(f);
    if (problem) {
      setMsg({ kind: "bad", text: problem });
      return;
    }
    await run(d.id, async () => {
      await api.replaceResume(d.id, { file_name: f.name, content_base64: toBase64(new Uint8Array(await f.arrayBuffer())) });
    }, `“${d.label}” replaced. Its Skill Match profile's skills were read again; the skills you added stay.`);
  }

  function confirmDelete(d: Doc) {
    const text = kind === "resume"
      ? `Delete “${d.label}”?

Its Skill Match profile is deleted too, with any skills you added there. Jobs are scored again with your other resumes.`
      : `Delete “${d.label}”?`;
    if (window.confirm(text)) void run(d.id, () => (kind === "resume" ? api.deleteResume(d.id) : api.deleteCoverLetter(d.id)));
  }

  async function savePaste() {
    await run("paste", async () => {
      const body = { text: paste.text, label: paste.label.trim() || null };
      if (kind === "resume") await api.addResume(body);
      else await api.addCoverLetter(body);
      setPasting(false);
      setPaste({ label: "", text: "" });
    }, `${c.noun[0]!.toUpperCase()}${c.noun.slice(1)} added.`);
  }

  async function download(d: Doc) {
    try {
      downloadBlob(kind === "resume" ? await api.resumeFile(d.id) : await api.coverLetterFile(d.id), d.file_name ?? d.label);
    } catch (e) {
      setMsg({ kind: "bad", text: errorMessage(e) });
    }
  }

  async function fill(d: Doc) {
    if (!onFill) return;
    setBusy(d.id);
    setMsg(null);
    try {
      onFill(await api.candidateFromResume(d.id), d.label);
    } catch (e) {
      setMsg({ kind: "bad", text: errorMessage(e) });
    } finally {
      setBusy(null);
    }
  }

  const full = docs !== null && docs.length >= limit;
  return (
    <section className="card" id={kind === "resume" ? "resumes" : "cover-letters"} data-testid={`${c.testid}-library`}>
      <div className="card-head">
        <h2>{c.title}</h2>
        <div className="row">
          <button type="button" className="btn btn-sm" disabled={full || busy !== null} onClick={() => input.current?.click()}>
            {busy === "upload" ? "Uploading…" : `Upload ${c.noun}`}
          </button>
          <button type="button" className="btn btn-sm btn-ghost" disabled={full} onClick={() => setPasting((p) => !p)}>Paste text</button>
          <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={upload} data-testid={`${c.testid}-input`} />
          {kind === "resume" ? (
            <input ref={replaceInput} type="file" accept={ACCEPT} hidden onChange={replace} data-testid="resume-replace-input" />
          ) : null}
        </div>
      </div>
      {docs ? <p className="subtle" style={{ marginTop: 0 }}>{c.hint(docs.length, limit)}</p> : null}
      {msg ? <div style={{ marginBottom: 10 }}><Notice kind={msg.kind}>{msg.text}</Notice></div> : null}
      {pasting ? (
        <div className="stack" style={{ marginBottom: 12 }}>
          <input className="input" aria-label={`${c.noun} name`} placeholder="Name (optional), e.g. Cloud and AI" value={paste.label}
            onChange={(e) => setPaste((p) => ({ ...p, label: e.target.value }))} />
          <textarea className="textarea" rows={8} aria-label={`${c.noun} text`} placeholder={`Paste the whole ${c.noun}`} value={paste.text}
            onChange={(e) => setPaste((p) => ({ ...p, text: e.target.value }))} />
          <div className="row">
            <button type="button" className="btn btn-primary btn-sm" disabled={busy !== null || paste.text.trim().length < 100} onClick={savePaste}>Save</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPasting(false)}>Cancel</button>
          </div>
        </div>
      ) : null}
      {docs === null ? (
        <div className="loading">Loading…</div>
      ) : docs.length === 0 ? (
        <p className="muted">
          {kind === "resume"
            ? "No resume yet. Upload one (PDF, Word, OpenDocument, RTF or text) to score your jobs and fill your profile."
            : "No cover letters yet. Add the ones you use; the best fit is suggested for each job."}
        </p>
      ) : (
        <ul className="doc-list">
          {docs.map((d) => (
            <li key={d.id} data-testid={`${c.testid}-item`}>
              <div className="grow">
                {renaming?.id === d.id ? (
                  <form className="row" onSubmit={(e) => {
                    e.preventDefault();
                    void run(d.id, () => kind === "resume"
                      ? api.updateResume(d.id, { label: renaming.label, version: d.version })
                      : api.updateCoverLetter(d.id, { label: renaming.label, version: d.version }));
                    setRenaming(null);
                  }}>
                    <input className="input narrow" aria-label="New name" value={renaming.label} autoFocus
                      onChange={(e) => setRenaming({ id: d.id, label: e.target.value })} />
                    <button className="btn btn-sm">Save</button>
                    <button type="button" className="btn btn-sm btn-ghost" onClick={() => setRenaming(null)}>Cancel</button>
                  </form>
                ) : (
                  <div className="row">
                    <strong>{d.label}</strong>
                    {d.is_main ? <span className="badge badge-info">{c.main}</span> : null}
                  </div>
                )}
                <div className="subtle">
                  {d.file_kind ? `${d.file_kind.toUpperCase()} · ${sizeLabel(d.file_size)}` : "Pasted text"} · {d.characters.toLocaleString()} characters
                </div>
              </div>
              <div className="row">
                {onFill ? (
                  <button type="button" className="btn btn-sm" disabled={busy !== null} onClick={() => fill(d)}
                    aria-label={`Fill profile from ${d.label}`}>Fill profile</button>
                ) : null}
                {!d.is_main ? (
                  <button type="button" className="btn btn-sm btn-ghost" disabled={busy !== null}
                    onClick={() => run(d.id, () => (kind === "resume" ? api.makePrimaryResume(d.id) : api.makeDefaultCoverLetter(d.id)))}
                    aria-label={`${c.makeMain}: ${d.label}`}>{c.makeMain}</button>
                ) : null}
                {kind === "resume" ? (
                  <button type="button" className="btn btn-sm btn-ghost" disabled={busy !== null} aria-label={`Replace file: ${d.label}`}
                    title="Upload a new version. It keeps its name and Skill Match profile."
                    onClick={() => { setReplacing(d); replaceInput.current?.click(); }}>Replace file</button>
                ) : null}
                {d.file_name ? <button type="button" className="btn btn-sm btn-ghost" onClick={() => download(d)}>Download</button> : null}
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => setRenaming({ id: d.id, label: d.label })}>Rename</button>
                <button type="button" className="btn btn-sm btn-ghost danger" disabled={busy !== null} aria-label={`Delete ${d.label}`}
                  onClick={() => confirmDelete(d)}>
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function DocumentLibrary({ onFill }: { onFill: (draft: CandidateDraft, label: string) => void }) {
  return (
    <>
      <Library kind="resume" onFill={onFill} />
      <Library kind="letter" />
    </>
  );
}
