// POC (user, 2026-11-17): an "Add to BrewMyJob" button next to each LinkedIn, Naukri or Foundit job result on
// Google's search page. On the user's click it sends what Google shows (link, title, snippet) to BrewMyJob; the
// portal page is never opened. Runs only on Google's results (manifest "content_scripts").
// To remove the POC: see backend/app/modules/extension/google.py.
(() => {
  // The parts of each portal that hold single job pages (backend/app/modules/jobs/found.py, PORTALS).
  const JOB_PAGE = /^https?:\/\/([a-z]+\.)?(linkedin\.com\/jobs\/view|naukri\.com\/job-listings|foundit\.in\/job)/i;
  const MARK = "data-bmj";

  /** The real link behind Google's redirect (/url?q=…), or the link itself. @param {string} href */
  function target(href) {
    try {
      const u = new URL(href, location.protocol.startsWith("http") ? location.href : "https://www.google.com/");
      if (/(^|\.)google\.[a-z.]+$/.test(u.hostname) && u.pathname === "/url") {
        return u.searchParams.get("url") || u.searchParams.get("q") || href;
      }
      return u.href;
    } catch {
      return href;
    }
  }

  /** Link, title and snippet of the result a title link belongs to, or null when it isn't a portal job page. */
  function resultOf(a) {
    const h3 = a.querySelector("h3");
    const url = target(a.getAttribute("href") || "");
    if (!h3 || !JOB_PAGE.test(url)) return null;
    const block = a.closest("div.g, div.MjjYud, div[data-hveid]") || a.parentElement;
    const title = h3.innerText.trim();
    const box = block && block.querySelector(".VwiC3b, [data-sncf], [style*='line-clamp']");
    let snippet = box ? box.innerText : "";
    if (!snippet && block) snippet = block.innerText.replace(title, "").replace(a.innerText, "");
    snippet = snippet.replace(/\s+/g, " ").trim().slice(0, 600);
    return { url, title, snippet: snippet || null };
  }

  function button(result) {
    const wrap = document.createElement("span");
    wrap.setAttribute("data-testid", "bmj-add");
    wrap.style.cssText = "display:inline-flex;gap:8px;align-items:center;margin:4px 0 6px;font:13px/1.4 system-ui,sans-serif";
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = "+ Add to BrewMyJob";
    b.style.cssText =
      "border:1px solid #4f46e5;color:#4f46e5;background:#fff;border-radius:999px;padding:2px 10px;cursor:pointer;font:inherit";
    const note = document.createElement("span");
    note.style.color = "#555";
    b.onclick = async (e) => {
      e.preventDefault();
      e.stopPropagation();
      b.disabled = true;
      b.textContent = "Adding…";
      try {
        // After the extension is reloaded, a Google tab opened before keeps an orphaned script whose messages go
        // nowhere: say so instead of "Adding…" for ever.
        if (!chrome.runtime || !chrome.runtime.id) throw new Error("The extension was reloaded: reload this page.");
        const r = await Promise.race([
          chrome.runtime.sendMessage({ type: "google-result", ...result }),
          new Promise((_, no) =>
            setTimeout(() => no(new Error("No answer from the extension. Reload this page and try again.")), 20000),
          ),
        ]);
        if (!r || !r.ok) throw new Error((r && r.error) || "BrewMyJob didn't answer");
        const v = r.value;
        b.textContent = v.already ? "Already in your jobs" : "Added to From Google ✓";
        note.textContent = "";
        const open = document.createElement("a");
        open.href = v.link;
        open.target = "_blank";
        open.rel = "noopener";
        open.textContent = v.already ? "Open in BrewMyJob" : "Review in BrewMyJob";
        note.append(open);
      } catch (err) {
        b.disabled = false;
        b.textContent = "+ Add to BrewMyJob";
        note.textContent = String((err && err.message) || err);
        note.style.color = "#b91c1c";
      }
    };
    wrap.append(b, note);
    return wrap;
  }

  function scan(root = document) {
    for (const a of root.querySelectorAll("a[href]")) {
      if (a.hasAttribute(MARK)) continue;
      const result = resultOf(a);
      if (!result) continue;
      a.setAttribute(MARK, "1");
      const line = a.closest("div") || a.parentElement;
      if (line && line.parentElement) line.parentElement.insertBefore(button(result), line.nextSibling);
    }
  }

  globalThis.BrewMyJobGoogle = { scan, resultOf, target };
  scan();
  // Google adds results as you scroll ("more results"): mark those too.
  let pending = false;
  new MutationObserver(() => {
    if (pending) return;
    pending = true;
    setTimeout(() => {
      pending = false;
      scan();
    }, 300);
  }).observe(document.body, { childList: true, subtree: true });
})();
