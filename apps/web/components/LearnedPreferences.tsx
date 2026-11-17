"use client";
import type { Learned } from "@fitfirst/api";
import { useEffect, useState } from "react";
import { errorMessage, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { seenAgo } from "@/lib/jobs";

/** What BrewMyJob learned from "Not for me" (milestone 13 A). Jobs like these score at most 40; removing one
 * re-scores every job. */
export function LearnedPreferences() {
  const [items, setItems] = useState<Learned[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.learnedPreferences().then(setItems).catch((e) => setError(errorMessage(e)));
  }, []);

  async function forget(id: string) {
    setBusy(id);
    setError(null);
    try {
      await api.forgetPreference(id);
      setItems((xs) => (xs ?? []).filter((x) => x.id !== id));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="card" id="learned" style={{ scrollMarginTop: 16 }} data-testid="learned">
      <div className="card-head">
        <h2>Learned from your feedback</h2>
        <span className="subtle">From &quot;Not for me&quot; on a job</span>
      </div>
      {error ? <Notice kind="bad">{error}</Notice> : null}
      {items === null ? (
        <p className="subtle">Loading…</p>
      ) : !items.length ? (
        <p className="subtle" style={{ margin: 0 }}>
          Nothing yet. When you say a job is not for you because of its company, city, field or level, jobs like it score
          lower, and the reason is listed here.
        </p>
      ) : (
        <>
          <p className="hint" style={{ marginTop: 0 }}>Jobs like these score at most 40 and sit in Other jobs. Remove one to score them on their merits again.</p>
          <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {items.map((p) => (
              <li key={p.id} style={{ display: "flex", gap: 12, alignItems: "center", justifyContent: "space-between" }} data-testid="learned-item">
                <span>
                  <strong>{p.label}</strong> <span className="subtle">· {seenAgo(p.created_at)}</span>
                </span>
                <button className="btn btn-sm btn-ghost" disabled={busy === p.id} onClick={() => void forget(p.id)} aria-label={`Remove ${p.label}`}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
