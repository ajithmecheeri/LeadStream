"use client";
import type { PairedBrowser } from "@fitfirst/api";
import { useEffect, useState } from "react";
import { errorMessage, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { seenAgo } from "@/lib/jobs";

/** Settings → Browser extension (milestone 14.3): pair the BrewMyJob extension with a one-time code, see and unpair
 * browsers. The extension fills company application forms when you click; never on job portals; never submits. */
export function BrowserExtension() {
  const [devices, setDevices] = useState<PairedBrowser[] | null>(null);
  const [code, setCode] = useState<{ code: string; expires_at: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => api.extensionDevices().then(setDevices).catch((e) => setError(errorMessage(e)));
  useEffect(() => {
    void load();
  }, []);

  async function makeCode() {
    setBusy(true);
    setError(null);
    try {
      setCode(await api.extensionPairingCode());
      setCopied(false);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function unpair(id: string) {
    setBusy(true);
    try {
      await api.unpairExtension(id);
      setDevices((ds) => (ds ?? []).filter((d) => d.id !== id));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card stack" style={{ marginTop: 16 }} data-testid="browser-extension">
      <div className="card-head">
        <h2>Browser extension</h2>
        <span className="subtle">Chrome and Edge</span>
      </div>
      <p style={{ margin: 0 }}>
        On a company&apos;s application form (Greenhouse, Lever, Ashby, SmartRecruiters, Workday), click <strong>Fill with BrewMyJob</strong> and
        it fills what it knows from your profile. It never clicks Submit, never signs in or signs up, and it doesn&apos;t work on job portals such as
        LinkedIn or Naukri; use the Apply kit on the job page there.
      </p>
      <p style={{ margin: 0 }}>
        It also puts an <strong>Add to BrewMyJob</strong> button on Google&apos;s results for LinkedIn, Naukri and Foundit jobs; they wait in
        Jobs → From Google for you to review.
      </p>
      {/* Download and install (user, 2026-11-17): the zip is built into the web app. */}
      <div className="stack" style={{ gap: 6 }} data-testid="extension-download">
        <div>
          <a className="btn btn-sm btn-primary" href="/downloads/brewmyjob-extension.zip" download>Download the extension</a>
        </div>
        <ol className="hint" style={{ margin: 0, paddingLeft: 18 }}>
          <li>Unzip the download into a folder you keep (Chrome loads it from there).</li>
          <li>Open <code>chrome://extensions</code> (Edge: <code>edge://extensions</code>) and turn on <strong>Developer mode</strong>.</li>
          <li>Click <strong>Load unpacked</strong> and choose the unzipped <code>brewmyjob-extension</code> folder.</li>
          <li>Pin BrewMyJob from the puzzle-piece menu, then click <strong>Pair a browser</strong> below and paste the code into the extension.</li>
        </ol>
        <p className="subtle" style={{ margin: 0 }}>After an update, download it again, replace the folder and press reload on the extension.</p>
      </div>
      {error ? <Notice kind="bad">{error}</Notice> : null}
      {code ? (
        <div className="stack" style={{ gap: 6 }} data-testid="pairing-code">
          <code style={{ wordBreak: "break-all", padding: 8, background: "var(--panel-2)", borderRadius: 8 }}>{code.code}</code>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button type="button" className="btn btn-sm" onClick={() => void navigator.clipboard.writeText(code.code).then(() => setCopied(true))}>
              {copied ? "Copied" : "Copy code"}
            </button>
            <span className="subtle">Works once, until {new Date(code.expires_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}.</span>
          </div>
        </div>
      ) : null}
      <div>
        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void makeCode()}>{code ? "Make a new code" : "Pair a browser"}</button>
      </div>
      {devices?.length ? (
        <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {devices.map((d) => (
            <li key={d.id} style={{ display: "flex", gap: 12, justifyContent: "space-between", alignItems: "center" }} data-testid="paired-browser">
              <span>
                <strong>{d.name ?? "A browser"}</strong>{" "}
                <span className="subtle">· paired {d.paired_at ? seenAgo(d.paired_at) : ""}{d.last_used_at ? ` · last used ${seenAgo(d.last_used_at).toLowerCase()}` : ""}</span>
              </span>
              <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => void unpair(d.id)} aria-label={`Unpair ${d.name ?? "browser"}`}>Unpair</button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
