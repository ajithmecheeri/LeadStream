// BrewMyJob extension: fills the application form on the page in view (milestone 14.4–14.5). Injected by
// background.js only when the user clicks "Fill this page", after match.js. It never clicks Submit or Next, never
// signs in or up, skips sensitive questions, only fills empty fields, and marks what it filled (green) and what
// still needs the user (amber). Sets globalThis.BrewMyJobFill.
(() => {
  const M = globalThis.BrewMyJobMatch;
  const FILLED = "2px solid #2E7D32";
  const NEEDS_YOU = "2px solid #D97706";
  const sleep = (/** @type {number} */ ms) => new Promise((r) => setTimeout(r, ms));
  const text = (/** @type {Element | null | undefined} */ el) => (el?.textContent || "").replace(/\s+/g, " ").trim();

  /** The question a field asks, as the user sees it. @param {HTMLElement} el */
  function labelOf(el) {
    const wd = el.closest("[data-automation-id^='formField-']");
    if (wd) {
      const l = wd.querySelector("label, legend");
      if (l) return text(l);
    }
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return text(l);
    }
    const aria = el.getAttribute("aria-label");
    if (aria) return aria;
    const by = el.getAttribute("aria-labelledby");
    if (by) return by.split(/\s+/).map((id) => text(document.getElementById(id))).join(" ");
    const wrap = el.closest("label");
    if (wrap) return text(wrap);
    const box = el.closest(".field, .application-question, .form-group, li, [class*='question'], [class*='field']");
    const l = box?.querySelector("label, .label, .text, legend, [class*='label']");
    if (l && l !== el) return text(l);
    return el.getAttribute("placeholder") || el.getAttribute("name") || el.id || "";
  }

  /** Set a value the way typing would, so React and Angular forms notice. @param {HTMLInputElement | HTMLTextAreaElement} el @param {string} value */
  function setValue(el, value) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  /** Type a value as a person would: Workday's month and year boxes ignore a value that is only set.
   * @param {HTMLInputElement} el @param {string} value */
  function typeValue(el, value) {
    el.focus();
    el.select?.();
    // insertText goes through the browser's own input path, which Workday's date widget listens to.
    if (!document.execCommand("insertText", false, value) || el.value !== value) setValue(el, value);
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  /** @param {HTMLSelectElement} el @param {string} value */
  function setSelect(el, value) {
    const opt = M.pickOption([...el.options].map((o) => ({ text: o.text, value: o.value })), value);
    if (!opt) return false;
    el.value = opt.value;
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  /** Workday's dropdowns: a button that opens a listbox. @param {HTMLElement} button @param {string} value */
  async function workdayChoose(button, value) {
    button.click();
    await sleep(400);
    const options = [...document.querySelectorAll("[role='option']")];
    const opt = M.pickOption(options.map((o, i) => ({ text: text(o), value: String(i) })), value);
    if (!opt) {
      document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      return false;
    }
    /** @type {HTMLElement} */ (options[Number(opt.value)]).click();
    await sleep(200);
    return true;
  }

  /** @param {File | null} file @param {HTMLInputElement} input */
  function attach(input, file) {
    if (!file) return false;
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  /** @param {{name: string, type: string, base64: string} | null | undefined} f */
  function toFile(f) {
    if (!f) return null;
    const bytes = Uint8Array.from(atob(f.base64), (c) => c.charCodeAt(0));
    return new File([bytes], f.name, { type: f.type });
  }

  const visible = (/** @type {HTMLElement} */ el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);

  // Numbered blocks by their heading ("Work Experience 2", "Education 1"): Workday's newer pages (2026-11-10, a real
  // JioStar form) and other forms that number them. The heading in force is the last one before the field.
  const ENTRY_HEADING = /^(work experience|employment|experience|education)\s*(\d+)/i;
  /** @type {Record<string, [string, RegExp][]>} */
  const ENTRY_FIELDS = {
    work: [
      ["title", /job title|^title|position|designation/i],
      ["company", /company|employer|organi[sz]ation/i],
      ["location", /location/i],
      ["description", /description|responsibilit/i],
    ],
    education: [
      ["school", /school|universit|college|institut/i],
      ["degree", /degree|qualification/i],
      ["field", /field of study|major|discipline/i],
    ],
  };

  /** Every "Work Experience 2" / "Education 1" heading on the page, in page order, whatever element holds it (a
   * real Workday page puts it in a plain div). */
  /** @type {Element[] | null} */
  let headingCache = null; // one page walk per Fill
  function entryHeadings() {
    if (headingCache) return headingCache;
    /** @type {Element[]} */
    const out = (headingCache = []);
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      const t = (n.textContent || "").replace(/\s+/g, " ").trim();
      if (t.length < 40 && ENTRY_HEADING.test(t) && n.parentElement && !n.parentElement.closest("label, option, script, style")) {
        out.push(n.parentElement);
      }
    }
    return out;
  }

  const norm = (/** @type {string | null | undefined} */ s) => (s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

  /** The numbered block a field is in, and the profile entry for it. A block whose Company is already filled
   * (Workday's own "Autofill with resume") gets the entry with that company, whatever its number; otherwise the
   * Nth block gets the Nth entry. @param {Element} el @param {any} data */
  function entryFor(el, data) {
    const headings = entryHeadings();
    let at = -1;
    headings.forEach((h, i) => { if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) at = i; });
    if (at < 0) return null;
    const m = text(headings[at]).match(ENTRY_HEADING);
    if (!m) return null;
    const kind = /education/i.test(m[1]) ? "education" : "work";
    const list = (kind === "work" ? data.work_history : data.education) || [];
    const next = headings[at + 1];
    // The block's fields: after its heading and before the next one.
    const fields = [...document.querySelectorAll("input, textarea")].filter((f) =>
      (headings[at].compareDocumentPosition(f) & Node.DOCUMENT_POSITION_FOLLOWING) &&
      !(next && next.compareDocumentPosition(f) & Node.DOCUMENT_POSITION_FOLLOWING));
    const named = fields.find((f) => /company|employer|school|universit/i.test(labelOf(/** @type {HTMLElement} */ (f))) && /** @type {HTMLInputElement} */ (f).value);
    const said = named && norm(/** @type {HTMLInputElement} */ (named).value);
    const byName = said
      ? list.find((x) => { const c = norm(kind === "work" ? x.company : x.school); return c && (c.includes(said) || said.includes(c)); })
      : null;
    if (said && !byName) return { kind, entry: null }; // a role BrewMyJob doesn't have: leave it to the user
    return { kind, entry: byName || list[Number(m[2]) - 1] || null };
  }

  /** A start or end date box in a numbered work block: Workday's month and year parts, or one "MM/YYYY" box.
   * @param {HTMLInputElement} el */
  function entryDate(el, entry) {
    if (!entry) return null;
    const names = `${el.getAttribute("data-automation-id") || ""} ${el.id} ${el.getAttribute("aria-label") || ""}`;
    const hint = el.getAttribute("placeholder") || "";
    const part = /month/i.test(names) ? "month" : /year/i.test(names) ? "year" : /mm.*yyyy/i.test(hint) ? "both" : null;
    if (!part) return null;
    const box = el.closest("[data-automation-id*='startDate'], [data-automation-id*='endDate'], [id*='startDate'], [id*='endDate']");
    const label = labelOf(el);
    const end = box ? /endDate/.test(box.getAttribute("data-automation-id") || box.id)
      : /^\s*(to|end)\b/i.test(label) ? true : /^\s*(from|start)\b/i.test(label) ? false : null;
    if (end === null) return null;
    const ym = end ? (entry.current ? null : entry.end) : entry.start;
    if (!ym) return null;
    const [y, m] = ym.split("-");
    return part === "year" ? y : part === "month" ? m : `${m}/${y}`;
  }

  /** Fill by Workday's own field names (data-automation-id), section by section. */
  async function workday(data, report) {
    const f = data.fields;
    const byId = {
      "legalNameSection_firstName": f.first_name,
      "legalNameSection_lastName": f.last_name,
      "email": f.email,
      "phone-number": f.phone,
      "phoneNumber": f.phone,
      "addressSection_addressLine1": f.address_line1,
      "addressSection_addressLine2": f.address_line2,
      "addressSection_city": f.city,
      "addressSection_postalCode": f.postal_code,
    };
    for (const [id, value] of Object.entries(byId)) {
      for (const el of document.querySelectorAll(`input[data-automation-id='${id}']`)) {
        if (value && !el.value) { setValue(el, value); mark(el, report, true); }
      }
    }
    for (const [id, value] of [["addressSection_countryRegion", f.state], ["countryDropdown", f.country]]) {
      const b = document.querySelector(`button[data-automation-id='${id}']`);
      if (b && value && /select one/i.test(text(b))) mark(b, report, await workdayChoose(b, value));
    }
    // Work experience and education: fill the blocks on the page; "Add" (not Submit) opens one more.
    await repeated(data.work_history, "workExperienceSection", report, async (block, w) => {
      put(block, "jobTitle", w.title, report);
      put(block, "company", w.company, report);
      put(block, "location", w.location, report);
      put(block, "description", w.description, report);
      const now = block.querySelector("input[type='checkbox'][data-automation-id='currentlyWorkHere']");
      if (now && w.current && !now.checked) { now.click(); report.filled++; }
      date(block, "startDate", w.start, report);
      if (!w.current) date(block, "endDate", w.end, report);
    });
    await repeated(data.education, "educationSection", report, async (block, e) => {
      put(block, "school", e.school, report) || put(block, "schoolName", e.school, report);
      put(block, "firstYearAttended", e.start_year, report, true);
      put(block, "lastYearAttended", e.end_year, report, true);
      const deg = block.querySelector("button[data-automation-id='degree']");
      if (deg && e.degree && /select one/i.test(text(deg))) mark(deg, report, await workdayChoose(deg, e.degree));
    });
  }

  /** @returns {boolean} */
  function put(block, id, value, report, year = false) {
    const el = block.querySelector(`[data-automation-id='${id}'] input, input[data-automation-id='${id}'], textarea[data-automation-id='${id}'], ` +
      `input[name='${id}'], textarea[name='${id}'], input[id$='--${id}'], textarea[id$='--${id}']` +
      `${year ? ", [data-automation-id='" + id + "'] [data-automation-id='dateSectionYear-input']" : ""}`);
    if (!el || el.value || value == null || value === "") return !!el;
    setValue(el, String(value));
    mark(el, report, true);
    return true;
  }

  function date(block, id, ym, report) {
    if (!ym) return;
    const [y, m] = ym.split("-");
    const box = block.querySelector(`[data-automation-id='${id}']`) || block.querySelector(`[data-automation-id*='${id}']`);
    if (!box) return;
    const month = box.querySelector("[data-automation-id='dateSectionMonth-input']");
    const year = box.querySelector("[data-automation-id='dateSectionYear-input']");
    if (month && !month.value) { typeValue(month, String(Number(m))); mark(month, report, true); }
    if (year && !year.value) { typeValue(year, y); mark(year, report, true); }
  }

  async function repeated(entries, sectionId, report, fillBlock) {
    const section = document.querySelector(`[data-automation-id='${sectionId}']`);
    if (!section || !entries?.length) return;
    const blocks = () => [...section.querySelectorAll("[data-automation-id^='formField-'], [role='group']")]
      .map((el) => el.closest("[data-fkit-id], [role='group']") || el)
      .filter((el, i, all) => all.indexOf(el) === i);
    for (let i = 0; i < entries.length; i++) {
      let list = blocks();
      if (i >= list.length) {
        const add = [...section.querySelectorAll("button")].find((b) => /^add( another)?$/i.test(text(b)) || b.getAttribute("data-automation-id") === "Add");
        if (!add) break;
        add.click();
        await sleep(500);
        list = blocks();
        if (i >= list.length) break;
      }
      await fillBlock(list[i], entries[i]);
    }
  }

  /** @param {HTMLElement} el @param {{filled: number, needs: string[]}} report @param {boolean} ok */
  function mark(el, report, ok, label) {
    el.style.outline = ok ? FILLED : NEEDS_YOU;
    el.dataset.brewmyjob = ok ? "filled" : "needs-you";
    if (ok) report.filled++;
    else if (label) report.needs.push(label);
  }

  /** Every other field, by its label: works on Greenhouse, Lever, Ashby, SmartRecruiters and most forms. */
  async function byLabel(data, files, report) {
    const fields = /** @type {NodeListOf<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>} */ (
      document.querySelectorAll("input, textarea, select")
    );
    for (const el of fields) {
      if (el.dataset.brewmyjob || el.disabled || ("readOnly" in el && el.readOnly)) continue;
      const type = (el.getAttribute("type") || "").toLowerCase();
      if (type === "checkbox" && el instanceof HTMLInputElement && /currently work here/i.test(labelOf(el))) {
        const e = entryFor(el, data);
        if (e?.entry?.current && !el.checked) { el.click(); mark(el, report, true); }
        continue;
      }
      if (["hidden", "submit", "button", "password", "search", "checkbox", "radio", "reset", "image"].includes(type)) continue;
      const label = labelOf(el);
      if (type === "file") {
        const kind = M.fileKind(label);
        if (kind && !el.files?.length) mark(el, report, attach(el, files[kind]), label);
        continue;
      }
      if (el.value) continue;
      // Workday's month and year parts are near-invisible inputs under a visible "MM/YYYY" box.
      const datePart = /dateSection|month|year/i.test(`${el.getAttribute("data-automation-id") || ""} ${el.id}`);
      if (!visible(el) && !(datePart && el.parentElement && visible(el.parentElement))) continue;
      if (M.isSensitive(label)) { report.skipped.push(label); continue; }
      // In a numbered block, the block's own fields come from that entry (and stay amber when it has no value).
      const e = entryFor(el, data);
      const own = e && ENTRY_FIELDS[e.kind].find(([, re]) => re.test(label));
      const when = e?.kind === "work" && el instanceof HTMLInputElement ? entryDate(el, e.entry) : null;
      const key = M.keyFor(label);
      const value = when ?? (own ? e.entry?.[own[0]] : (key && data.fields[key]) || M.answerFor(label, data.answers));
      if (!value) {
        // Workday and others mark required fields only with an asterisk in the label.
        if (el.required || el.getAttribute("aria-required") === "true" || /\*\s*$/.test(label)) mark(el, report, false, label);
        continue;
      }
      if (el instanceof HTMLSelectElement) mark(el, report, setSelect(el, value), label);
      // A block's own fields are typed: Workday's form state only follows real input.
      else if (when !== null || own) { typeValue(/** @type {HTMLInputElement} */ (el), String(value)); mark(el, report, true); }
      else { setValue(el, value); mark(el, report, true); }
    }
  }

  function toast(report, data) {
    document.getElementById("brewmyjob-toast")?.remove();
    const box = document.createElement("div");
    box.id = "brewmyjob-toast";
    box.setAttribute("role", "status");
    box.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;max-width:340px;background:#1E1712;color:#fff;" +
      "font:14px/1.45 system-ui,sans-serif;padding:12px 14px;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.25)";
    const needs = report.needs.length ? ` ${report.needs.length} need you (amber).` : "";
    const skipped = report.skipped.length ? ` ${report.skipped.length} personal question(s) left for you.` : "";
    const f = data.fields || {};
    const empty = !f.phone && !f.address_line1 && !f.city && !(data.work_history || []).length && !(data.education || []).length
      ? " Your application details are empty: in BrewMyJob, fill in Profile → For application forms, then click Fill again."
      : "";
    box.textContent = `BrewMyJob filled ${report.filled} field(s) (green).${needs}${skipped}${empty} Check everything, then click Next or Submit yourself.`;
    const close = document.createElement("button");
    close.textContent = "×";
    close.setAttribute("aria-label", "Close");
    close.style.cssText = "margin-left:8px;background:none;border:0;color:#fff;font-size:18px;cursor:pointer";
    close.onclick = () => box.remove();
    box.appendChild(close);
    document.body.appendChild(box);
  }

  /** Fill the page in view. @returns {Promise<{filled: number, needs: string[], skipped: string[], system: string}>} */
  async function run(data, rawFiles) {
    if (M.isBlocked(location.hostname)) throw new Error("BrewMyJob doesn't fill forms on job portals");
    const report = { filled: 0, needs: [], skipped: [], system: M.system(location.hostname) };
    headingCache = null;
    const files = { resume: toFile(rawFiles?.resume), cover_letter: toFile(rawFiles?.cover_letter) };
    if (report.system === "workday") await workday(data, report);
    await byLabel(data, files, report);
    if (window === window.top) toast(report, data);
    return report;
  }

  globalThis.BrewMyJobFill = { run, labelOf };
})();
