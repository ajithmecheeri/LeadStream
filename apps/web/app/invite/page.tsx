"use client";
import type { InviteView } from "@fitfirst/api";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { errorMessage, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { PENDING_INVITE, useSession } from "@/lib/session";

/** An invite's link (user, 2026-11-17): sign up with it, or sign in with the invited email and accept. */
export default function InvitePage() {
  const { status, me, setMe, signOut } = useSession();
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [invite, setInvite] = useState<InviteView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("token");
    setToken(t);
    if (!t) return setError("This link has no invite in it. Open the link from your invite again.");
    api.viewInvite(t).then(setInvite).catch((e) => setError(errorMessage(e)));
  }, []);

  function remember() {
    try {
      if (token) sessionStorage.setItem(PENDING_INVITE, token);
    } catch {
      // storage blocked: accept after signing in by opening the link again
    }
  }

  async function accept() {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await api.acceptInvite(token);
      try {
        sessionStorage.removeItem(PENDING_INVITE);
      } catch {
        // nothing to clear
      }
      await api.refresh(); // a new token with the new role and period
      setMe(await api.me());
      router.replace("/dashboard");
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  }

  const offer = invite
    ? invite.role === "admin"
      ? "to join BrewMyJob as an admin"
      : invite.free_months
        ? `to use BrewMyJob free for ${invite.free_months} month${invite.free_months === 1 ? "" : "s"}`
        : "to join BrewMyJob"
    : "";
  const mine = me && invite && me.email.toLowerCase() === invite.email.toLowerCase();

  return (
    <main className="auth-wrap">
      <div className="card auth-card" data-testid="invite">
        <div className="brand">
          <span className="brand-mug" aria-hidden="true"><Icon name="mug" size={24} /></span>
          <span className="brand-mark">BMJ</span>BrewMyJob
        </div>
        <div className="stack">
          <h1>Your invite</h1>
          {error ? <Notice kind="bad">{error}</Notice> : null}
          {!invite && !error ? <p className="subtle">Loading…</p> : null}
          {invite ? (
            <>
              <p>
                <strong>{invite.email}</strong> is invited {offer}.
              </p>
              {status === "loading" ? null : status === "signed-in" ? (
                mine ? (
                  <button type="button" className="btn btn-primary" disabled={busy} onClick={accept}>
                    {busy ? "Accepting…" : "Accept the invite"}
                  </button>
                ) : (
                  <>
                    <Notice kind="info">You&apos;re signed in as {me?.email}. This invite is for {invite.email}.</Notice>
                    <button type="button" className="btn" onClick={signOut}>Sign out</button>
                  </>
                )
              ) : invite.has_account ? (
                <Link className="btn btn-primary" href="/sign-in" onClick={remember}>Sign in as {invite.email} to accept</Link>
              ) : (
                <Link className="btn btn-primary" href={`/sign-up?invite=${encodeURIComponent(token ?? "")}`}>
                  Create your account
                </Link>
              )}
            </>
          ) : null}
        </div>
      </div>
    </main>
  );
}
