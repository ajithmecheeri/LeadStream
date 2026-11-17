"use client";
import type { NotificationSettings } from "@fitfirst/api";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { errorMessage, Field, Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { WhatsAppAlerts } from "@/components/WhatsAppAlerts";

const ZONES = ["Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Europe/London", "America/New_York", "America/Los_Angeles", "UTC"];
const hhmm = (t?: string | null) => (t ? t.slice(0, 5) : "");

export default function SettingsPage() {
  const { me, setMe } = useSession();
  const [names, setNames] = useState({ first: me?.first_name ?? "", middle: me?.middle_name ?? "", last: me?.last_name ?? "" });
  const [tz, setTz] = useState(me?.timezone ?? "Asia/Kolkata");
  const [ns, setNs] = useState<NotificationSettings | null>(null);
  const [msg, setMsg] = useState<{ kind: "good" | "bad"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.notificationSettings().then(setNs).catch((e) => setMsg({ kind: "bad", text: errorMessage(e) }));
  }, []);
  if (!me || !ns) return <div className="loading">Loading…</div>;
  const setN = <K extends keyof NotificationSettings>(k: K, v: NotificationSettings[K]) =>
    setNs((cur) => (cur ? { ...cur, [k]: v } : cur));

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!ns) return;
    setBusy(true);
    setMsg(null);
    try {
      setMe(await api.updateMe({ first_name: names.first, middle_name: names.middle.trim() || null, last_name: names.last, timezone: tz }));
      setNs(await api.saveNotificationSettings({
        ...ns, quiet_start: ns.quiet_start || null, quiet_end: ns.quiet_end || null,
      }));
      setMsg({ kind: "good", text: "Settings saved." });
    } catch (err) {
      setMsg({ kind: "bad", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
    <form onSubmit={save} noValidate>
      <PageHeader title="Settings" />
      {msg ? <div style={{ marginBottom: 16 }}><Notice kind={msg.kind}>{msg.text}</Notice></div> : null}
      <section className="card">
        <div className="card-head"><h2>Account</h2></div>
        <div className="grid-2">
          <div className="name-row span-all">
            <Field label="First name" htmlFor="first-name">
              <input id="first-name" className="input" value={names.first} onChange={(e) => setNames((n) => ({ ...n, first: e.target.value }))} />
            </Field>
            <Field label="Middle name" htmlFor="middle-name" hint="Optional">
              <input id="middle-name" className="input" value={names.middle} onChange={(e) => setNames((n) => ({ ...n, middle: e.target.value }))} />
            </Field>
            <Field label="Last name" htmlFor="last-name">
              <input id="last-name" className="input" value={names.last} onChange={(e) => setNames((n) => ({ ...n, last: e.target.value }))} />
            </Field>
          </div>
          <Field label="Email" htmlFor="email"><input id="email" className="input" value={me.email} disabled /></Field>
          <Field label="Time zone" htmlFor="tz" hint="Quiet hours, the daily digest use this.">
            <select id="tz" className="select" value={tz} onChange={(e) => setTz(e.target.value)}>
              {[...new Set([tz, ...ZONES])].map((z) => <option key={z}>{z}</option>)}
            </select>
          </Field>
          <Field label="Alert forwarding address" htmlFor="fwd" hint={<>Forward LinkedIn and Naukri job-alert emails here. <Link href="/settings/mail">Mail setup</Link></>}>
            <input id="fwd" className="input num" value={me.forwarding_address} readOnly />
          </Field>
        </div>
      </section>
      <section className="card">
        <div className="card-head"><h2>Notifications</h2><span className="subtle">WhatsApp alerts below; mobile push and email come later</span></div>
        <div className="grid-3">
          <label className="check"><input type="checkbox" checked={ns.push ?? true} onChange={(e) => setN("push", e.target.checked)} /><span>Mobile push</span></label>
          <label className="check"><input type="checkbox" checked={ns.email ?? true} onChange={(e) => setN("email", e.target.checked)} /><span>Email</span></label>
          <span />
          <Field label="Quiet hours start" htmlFor="qs"><input id="qs" className="input" type="time" value={hhmm(ns.quiet_start)} onChange={(e) => setN("quiet_start", e.target.value)} /></Field>
          <Field label="Quiet hours end" htmlFor="qe"><input id="qe" className="input" type="time" value={hhmm(ns.quiet_end)} onChange={(e) => setN("quiet_end", e.target.value)} /></Field>
          <Field label="Daily digest at" htmlFor="dg"><input id="dg" className="input" type="time" value={hhmm(ns.digest_time)} onChange={(e) => setN("digest_time", e.target.value)} /></Field>
          <Field label="Max job alerts per day" htmlFor="mp" hint="WhatsApp and push together"><input id="mp" className="input num" type="number" min={0} max={50} value={ns.max_push_per_day ?? 10} onChange={(e) => setN("max_push_per_day", Number(e.target.value))} /></Field>
          <Field label="Networking suggestions per day" htmlFor="nd"><input id="nd" className="input num" type="number" min={0} max={20} value={ns.network_daily_cap ?? 5} onChange={(e) => setN("network_daily_cap", Number(e.target.value))} /></Field>
          <Field label="Weekly invitation limit" htmlFor="nw" hint="LinkedIn caps invitations at roughly 100 a week."><input id="nw" className="input num" type="number" min={0} max={200} value={ns.network_weekly_limit ?? 100} onChange={(e) => setN("network_weekly_limit", Number(e.target.value))} /></Field>
        </div>
      </section>
      <div className="sticky-actions"><button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Save settings"}</button></div>
    </form>
    <WhatsAppAlerts timeZone={me.timezone} />
    </>
  );
}
