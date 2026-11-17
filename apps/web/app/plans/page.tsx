"use client";
import type { Plans } from "@fitfirst/api";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { errorMessage, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { useRequireSession } from "@/lib/session";

const inr = (n: number) => `₹${n.toLocaleString("en-IN")}`;

/** Choose a plan (user, 2026-11-17): a job seeker without a running plan or coupon lands here. Payments come
 *  later (backlog); until then an invite's coupon opens the app. */
export default function PlansPage() {
  const { status, me, signOut } = useRequireSession();
  const [data, setData] = useState<Plans | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "signed-in") return;
    api.plans().then(setData).catch((e) => setError(errorMessage(e)));
  }, [status]);

  if (status !== "signed-in" || !me) return <div className="loading">Loading…</div>;
  const active = data?.access.active ?? me.access.active;
  const until = data?.access.until ?? me.access.until;
  const cheapest = data ? Math.min(...data.plans.map((p) => p.price_inr / p.months)) : 0;

  return (
    <main className="auth-wrap">
      <div className="card auth-card" style={{ maxWidth: 760 }} data-testid="plans">
        <div className="brand">
          <span className="brand-mug" aria-hidden="true"><Icon name="mug" size={24} /></span>
          <span className="brand-mark">BMJ</span>BrewMyJob
        </div>
        <div className="stack">
          <div>
            <h1>{active ? "Your plan" : "Choose a plan"}</h1>
            <p className="muted">
              {active
                ? until
                  ? `You can use BrewMyJob until ${new Date(until).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })}.`
                  : "Your account doesn't need a plan."
                : `Hi ${me.first_name}, BrewMyJob is a paid service. Pick the period that suits your search.`}
            </p>
          </div>
          {error ? <Notice kind="bad">{error}</Notice> : null}
          {data ? (
            <ul className="plan-grid" aria-label="Plans">
              {data.plans.map((p) => {
                const perMonth = Math.round(p.price_inr / p.months);
                return (
                  <li key={p.id} className="card plan-card" data-testid="plan">
                    <strong>{p.label}</strong>
                    <span className="plan-price">{inr(p.price_inr)}</span>
                    <span className="subtle">
                      {p.months === 1 ? "per month" : `${inr(perMonth)} a month`}
                      {p.months > 1 && p.price_inr / p.months === cheapest ? " · best value" : ""}
                    </span>
                    <button type="button" className="btn btn-sm" disabled title="Payments open soon">
                      {data.payments_open ? "Choose" : "Coming soon"}
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : <p className="subtle">Loading the plans…</p>}
          {!data?.payments_open ? (
            <Notice kind="info">
              Online payment opens soon. Got an invite? Open the link in it: an invite with a coupon gives you free
              months straight away.
            </Notice>
          ) : null}
          <div className="row">
            {active ? <Link className="btn btn-primary" href="/dashboard">Go to your dashboard</Link> : null}
            <span className="spacer" />
            <span className="subtle">Signed in as {me.email}</span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={signOut}>Sign out</button>
          </div>
        </div>
      </div>
    </main>
  );
}
