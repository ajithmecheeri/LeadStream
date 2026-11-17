// BrewMyJob extension: talks to the BrewMyJob API and injects the filler into the page the user is looking at,
// only when they click "Fill this page" (activeTab). The token is kept in chrome.storage.local.
import "./match.js";

const M = globalThis.BrewMyJobMatch;
const DEFAULT_API = "http://localhost:8080";

async function settings() {
  const s = await chrome.storage.local.get(["api", "token", "name", "email"]);
  return { api: s.api || DEFAULT_API, token: s.token || null, name: s.name || null, email: s.email || null };
}

async function call(path, init = {}) {
  const { api, token } = await settings();
  const r = await fetch(api.replace(/\/$/, "") + path, {
    ...init,
    headers: { ...(init.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!r.ok) {
    let message = `BrewMyJob answered ${r.status}`;
    try {
      message = (await r.json()).error?.message || message;
    } catch {
      // not JSON
    }
    if (r.status === 401) await chrome.storage.local.remove(["token"]);
    throw new Error(message);
  }
  return r;
}

async function fileOf(path) {
  try {
    const r = await call(path);
    const disposition = r.headers.get("content-disposition") || "";
    const name = decodeURIComponent(disposition.split("UTF-8''")[1] || "resume");
    const buf = new Uint8Array(await r.arrayBuffer());
    let bin = "";
    for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
    return { name, type: r.headers.get("content-type") || "application/octet-stream", base64: btoa(bin) };
  } catch {
    return null; // pasted as text: nothing to attach
  }
}

async function fill(tab) {
  const url = new URL(tab.url);
  if (M.isBlocked(url.hostname)) {
    throw new Error("BrewMyJob doesn't fill forms on job portals. Use the Apply kit on the job's page.");
  }
  const data = await (await call(`/api/v1/extension/fill-data?url=${encodeURIComponent(tab.url)}`)).json();
  const files = {};
  for (const d of data.documents || []) {
    const kind = d.kind === "resume" ? "resumes" : "cover-letters";
    files[d.kind] = await fileOf(`/api/v1/extension/${kind}/${d.id}/file`);
  }
  await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ["src/match.js", "src/fill.js"] });
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id, allFrames: true },
    func: (d, f) => globalThis.BrewMyJobFill.run(d, f),
    args: [data, files],
  });
  const reports = results.map((r) => r.result).filter(Boolean);
  return {
    filled: reports.reduce((n, r) => n + r.filled, 0),
    needs: reports.flatMap((r) => r.needs),
    skipped: reports.flatMap((r) => r.skipped),
    system: reports[0]?.system || "other",
    job: data.job,
  };
}

// POC (user, 2026-11-17): add a job from a Google result the user clicked "Add to BrewMyJob" on (src/google.js).
async function addGoogleResult(msg) {
  const { api, token } = await settings();
  if (!token) throw new Error("Pair the BrewMyJob extension first (click its icon).");
  const r = await call("/api/v1/extension/google-result", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: msg.url, title: msg.title, snippet: msg.snippet }),
  });
  const out = await r.json();
  const base = api.replace(/\/$/, "");
  return { ...out, link: out.already ? `${base}/jobs/${out.user_job_id}` : `${base}/jobs?tab=review` };
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  (async () => {
    if (msg.type === "status") return settings();
    if (msg.type === "pair") {
      await chrome.storage.local.set({ api: msg.api || DEFAULT_API });
      const r = await call("/api/v1/extension/pair", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: msg.code, name: msg.name }),
      });
      const out = await r.json();
      await chrome.storage.local.set({ token: out.token, name: out.name, email: out.email });
      return settings();
    }
    if (msg.type === "unpair") {
      await chrome.storage.local.remove(["token", "name", "email"]);
      return settings();
    }
    if (msg.type === "fill") return fill(msg.tab);
    if (msg.type === "google-result") return addGoogleResult(msg); // POC 2026-11-17 (src/google.js)
    throw new Error("Unknown request");
  })().then(
    (value) => reply({ ok: true, value }),
    (e) => reply({ ok: false, error: String(e.message || e) }),
  );
  return true; // the reply comes later
});
