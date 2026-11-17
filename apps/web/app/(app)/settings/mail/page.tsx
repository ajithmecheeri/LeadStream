"use client";
import type { Mail } from "@fitfirst/api";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { errorMessage, Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

// The senders a Gmail filter should forward. BrewMyJob accepts only these (checked with DKIM on arrival).
const GMAIL_FILTER = "from:(jobalerts-noreply@linkedin.com OR jobs-noreply@linkedin.com OR naukri.com)";

/** Addresses the user forwards alerts from by hand, for when a filter can't be set up. */
function ForwardByHand({ mail, onChange }: { mail: Mail; onChange: (m: Mail) => void }) {
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const senders = mail.forward_senders ?? [];

  async function add(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const s = await api.addForwardSender(address.trim());
      onChange({ ...mail, forward_senders: [...senders, s] });
      setAddress("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setError(null);
    try {
      await api.removeForwardSender(id);
      onChange({ ...mail, forward_senders: senders.filter((s) => s.id !== id) });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <section className="card" data-testid="forward-by-hand">
      <div className="card-head">
        <h2>Forward alerts by hand</h2>
        <span className="subtle">If you can&apos;t set up a filter</span>
      </div>
      <p className="muted">
        Add the email address you forward from, then use your mail app&apos;s <b>Forward</b> button to send a LinkedIn or Naukri alert
        to your BrewMyJob address. Only alerts forwarded from these addresses are accepted. A filter is still better: it never
        forgets one.
      </p>
      {senders.length ? (
        <ul className="doc-list" style={{ marginTop: 8 }}>
          {senders.map((s) => (
            <li key={s.id} data-testid="forward-sender">
              <div className="grow"><strong>{s.address}</strong></div>
              <button className="btn btn-ghost btn-sm" onClick={() => remove(s.id)} aria-label={`Remove ${s.address}`}>Remove</button>
            </li>
          ))}
        </ul>
      ) : null}
      {senders.length < 3 ? (
        <form className="addr" style={{ marginTop: 8 }} onSubmit={add}>
          <input
            type="email"
            required
            placeholder="you@gmail.com"
            aria-label="Address you forward from"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
          />
          <button className="btn btn-sm" disabled={busy || !address.trim()}>{busy ? "Adding…" : "Add address"}</button>
        </form>
      ) : null}
      {error ? <div style={{ marginTop: 8 }}><Notice kind="bad">{error}</Notice></div> : null}
      <p className="hint" style={{ marginTop: 8 }}>
        BrewMyJob can&apos;t check that a hand-forwarded alert is unchanged, so its jobs never alter what other users see. The first
        time the same job arrives through a filter or a careers site, its details are confirmed.
      </p>
    </section>
  );
}

export default function MailSetupPage() {
  const { me, setMe } = useSession();
  const [mail, setMail] = useState<Mail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [rotating, setRotating] = useState(false);

  useEffect(() => {
    api.mail().then(setMail).catch((e) => setError(errorMessage(e)));
  }, []);

  const copy = async (what: string, text: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(what);
    setTimeout(() => setCopied(null), 1500);
  };

  async function rotate() {
    if (!window.confirm("Get a new address? Mail sent to the old one will be refused, so you'll need to update your Gmail forwarding.")) return;
    setRotating(true);
    try {
      const m = await api.rotateMailAddress();
      setMail(m);
      if (me) setMe({ ...me, forwarding_address: m.address });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setRotating(false);
    }
  }

  if (!mail) return error ? <Notice kind="bad">{error}</Notice> : <div className="loading">Loading…</div>;

  return (
    <>
      <p className="subtle" style={{ marginBottom: 8 }}><Link href="/settings">← Settings</Link></p>
      <PageHeader title="Mail setup" sub="Forward your LinkedIn and Naukri job alerts to BrewMyJob. Your passwords are never needed." />
      {error ? <div style={{ marginBottom: 16 }}><Notice kind="bad">{error}</Notice></div> : null}

      <section className="card">
        <div className="card-head">
          <h2>Your BrewMyJob address</h2>
          {mail.receiving ? (
            <span className="badge badge-good">Receiving · last email {new Date(mail.last_received_at!).toLocaleDateString("en-IN")}</span>
          ) : (
            <span className="badge">Nothing received yet</span>
          )}
        </div>
        <div className="addr">
          <code data-testid="mail-address">{mail.address}</code>
          <button className="btn btn-sm" onClick={() => copy("address", mail.address)}>{copied === "address" ? "Copied" : "Copy"}</button>
        </div>
        <p className="hint" style={{ marginTop: 8 }}>
          Only job alerts from LinkedIn and Naukri are accepted at this address; anything else is refused.{" "}
          <button className="btn btn-ghost btn-sm" disabled={rotating} onClick={rotate}>{rotating ? "Changing…" : "Get a new address"}</button>
        </p>
      </section>

      {mail.forwarding_code ? (
        <section className="card">
          <div className="card-head"><h2>Gmail confirmation code</h2><span className="subtle">{new Date(mail.forwarding_code_at!).toLocaleString("en-IN")}</span></div>
          <div className="addr">
            <code data-testid="forwarding-code">{mail.forwarding_code}</code>
            <button className="btn btn-sm" onClick={() => copy("code", mail.forwarding_code!)}>{copied === "code" ? "Copied" : "Copy"}</button>
          </div>
          <p className="hint" style={{ marginTop: 8 }}>Type this into Gmail (step 3 below) to confirm forwarding.</p>
        </section>
      ) : mail.forwarding_link ? (
        <section className="card">
          <div className="card-head"><h2>Confirm forwarding in Gmail</h2><span className="subtle">{new Date(mail.forwarding_code_at!).toLocaleString("en-IN")}</span></div>
          <a className="btn btn-primary" data-testid="forwarding-link" href={mail.forwarding_link} target="_blank" rel="noopener noreferrer">
            Open Gmail&apos;s confirmation page
          </a>
          <p className="hint" style={{ marginTop: 8 }}>Open it in the browser where you&apos;re signed in to Gmail, then press <b>Confirm</b>.</p>
        </section>
      ) : null}

      <section className="card">
        <div className="card-head"><h2>Gmail</h2><span className="subtle">About 3 minutes, once</span></div>
        <ol className="howto">
          <li>Open Gmail on a computer → ⚙ <b>Settings</b> → <b>See all settings</b> → <b>Forwarding and POP/IMAP</b>.</li>
          <li><b>Add a forwarding address</b>, paste your BrewMyJob address and press <b>Next → Proceed</b>.</li>
          <li>Gmail sends a confirmation email to BrewMyJob. Within a minute this page shows either a link (open it and press <b>Confirm</b>) or a code (type it into Gmail and press <b>Verify</b>). Leave forwarding itself <b>off</b>; the filter below forwards only job alerts.</li>
          <li>
            Search Gmail for the alerts with this query, then choose <b>Create filter</b> (the ⚙ in the search bar shows the option):
            <div className="addr" style={{ marginTop: 6 }}>
              <code>{GMAIL_FILTER}</code>
              <button className="btn btn-sm" onClick={() => copy("filter", GMAIL_FILTER)}>{copied === "filter" ? "Copied" : "Copy"}</button>
            </div>
          </li>
          <li>Tick <b>Forward it to</b>, pick your BrewMyJob address and press <b>Create filter</b>. New alerts now arrive here; check the <Link href="/inbox">Inbox</Link>.</li>
        </ol>
      </section>

      <ForwardByHand mail={mail} onChange={setMail} />

      <section className="card">
        <div className="card-head"><h2>Yahoo Mail and others</h2></div>
        <p className="muted">
          Outlook works like Gmail: a rule that forwards mail from the senders above. Yahoo Mail forwards everything or nothing, so
          BrewMyJob would refuse most of it: change the email your LinkedIn and Naukri alerts go to so they reach Gmail, or forward
          alerts by hand (above).
        </p>
        {mail.upload_enabled ? (
          <p className="hint" style={{ marginTop: 8 }}>
            Local development: you can also save an alert from Gmail (⋮ → <b>Download message</b>) and upload the .eml on the{" "}
            <Link href="/inbox">Inbox</Link> page.
          </p>
        ) : null}
      </section>
    </>
  );
}
