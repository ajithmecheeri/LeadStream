// BrewMyJob extension popup: pair, then "Fill this page" on a company application form.
const $ = (id) => document.getElementById(id);
const ask = (msg) =>
  chrome.runtime.sendMessage(msg).then((r) => {
    if (!r.ok) throw new Error(r.error);
    return r.value;
  });
const say = (text, kind = "") => {
  $("msg").textContent = text;
  $("msg").className = kind;
};

function show(s) {
  $("unpaired").hidden = !!s.token;
  $("paired").hidden = !s.token;
  $("api").value = s.api;
  if (s.token) $("who").textContent = `Paired with ${s.name || "your account"}${s.email ? ` (${s.email})` : ""}.`;
}

async function current() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

(async () => {
  show(await ask({ type: "status" }));
  const tab = await current();
  try {
    const host = new URL(tab.url).hostname;
    if (globalThis.BrewMyJobMatch.isBlocked(host)) {
      $("fill").disabled = true;
      $("site").textContent = `${host} is a job portal: BrewMyJob doesn't fill forms here. Use the Apply kit on the job's page.`;
    } else {
      $("site").textContent = `This page: ${host}`;
    }
  } catch {
    $("fill").disabled = true;
  }
})();

$("pair").onclick = async () => {
  say("Pairing…");
  try {
    const browser = navigator.userAgent.includes("Edg/") ? "Edge" : "Chrome";
    const name = `${browser} on ${navigator.platform || "this computer"}`;
    show(await ask({ type: "pair", api: $("api").value.trim(), code: $("code").value.trim(), name }));
    say("Paired. Open a company application form and click Fill this page.", "good");
  } catch (e) {
    say(e.message, "bad");
  }
};

$("fill").onclick = async () => {
  $("fill").disabled = true;
  say("Filling…");
  try {
    const r = await ask({ type: "fill", tab: await current() });
    const parts = [`Filled ${r.filled} field(s).`];
    if (r.needs.length) {
      parts.push(`${r.needs.length} need you: ${r.needs.slice(0, 4).join(", ")}${r.needs.length > 4 ? "…" : ""}.`);
    }
    if (r.skipped.length) parts.push(`Personal questions left for you: ${r.skipped.length}.`);
    if (r.job) parts.push(`Job: ${r.job.title}${r.job.company ? ` at ${r.job.company}` : ""}.`);
    parts.push("Review, then click Next or Submit yourself.");
    say(parts.join(" "), "good");
  } catch (e) {
    say(e.message, "bad");
  } finally {
    $("fill").disabled = false;
  }
};

$("unpair").onclick = async () => {
  show(await ask({ type: "unpair" }));
  say("Unpaired here. To stop the token everywhere, unpair it on BrewMyJob Settings too.");
};
