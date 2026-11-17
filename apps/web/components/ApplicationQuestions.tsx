"use client";
import type { Answer } from "@fitfirst/api";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AnswerRow } from "@/components/AnswerRow";
import { errorMessage, Notice } from "@/components/ui";
import { api } from "@/lib/api";

/** Profile → Application Autofill Information: the Yes/No questions company forms ask (work authorisation,
 * sponsorship, non-compete…), answered once from the answer bank. The extension picks the matching dropdown
 * option on the form when you click it. */
export function ApplicationQuestions() {
  const [items, setItems] = useState<Answer[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems((await api.answers()).items.filter((a) => (a.choices ?? []).length));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="card" data-testid="application-questions">
      <div className="card-head">
        <h2>Application questions</h2>
        <Link className="subtle" href="/profile?tab=answers">All screening answers</Link>
      </div>
      <p className="hint">
        Company forms ask these on almost every application. Answer once; the browser extension picks the same
        answer in the form&apos;s dropdown when you click Fill, and you check it before you submit.
      </p>
      {error ? <Notice kind="bad">{error}</Notice> : null}
      {items === null ? (
        <div className="loading">Loading…</div>
      ) : (
        <ul className="blockers">
          {items.map((a) => (
            <AnswerRow key={`${a.key}-${a.version ?? 0}-${a.answer ?? ""}`} a={a} onSaved={load} />
          ))}
        </ul>
      )}
    </section>
  );
}
