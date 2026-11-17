/** Labels, filters and small helpers for the Jobs, Inbox and Mail pages. Pure functions (unit-tested). */

export type Lead = "alert" | "recommendation" | "recruiter_invite" | "company_feed" | "job_board";
/** Within the match tabs: every active job, or only new ones. */
export type StatusFilter = "active" | "new";
/** The Jobs page queues. The first three split active jobs by match; the rest are jobs you've acted on. */
export type Tab = "top" | "other" | "unscored" | "applied" | "expired" | "ignored" | "all" | "review";
export const MATCH_TABS: readonly Tab[] = ["top", "other", "unscored"];
export const isMatchTab = (t: Tab) => MATCH_TABS.includes(t);
export type DateRange = "any" | "today" | "7d" | "30d" | "custom";

export const LEAD_LABEL: Record<Lead, string> = {
  alert: "Job alert",
  recommendation: "Recommended",
  recruiter_invite: "Recruiter invite",
  company_feed: "Company careers",
  job_board: "Job board",
};

const COMPANY_SITES = ["greenhouse", "lever", "ashby", "smartrecruiters", "workday", "oracle", "eightfold", "careers_page"];

export const SOURCE_LABEL: Record<string, string> = {
  linkedin: "LinkedIn",
  naukri: "Naukri",
  naukri_rdx: "Naukri recruiter",
  foundit: "Foundit",
  ...Object.fromEntries(COMPANY_SITES.map((s) => [s, "Company careers site"])),
  adzuna: "Adzuna",
  ai_assistant: "AI assistant alert",
};

/** Where a job came from, as people say it: "LinkedIn", "Naukri", "Adzuna", "Databricks careers site". */
export function sourceLabel(source: string, company?: string | null): string {
  if (COMPANY_SITES.includes(source)) return company ? `${company} careers site` : SOURCE_LABEL[source]!;
  return SOURCE_LABEL[source] ?? source;
}

/** Every source of a job once, in the order it should be named. */
export function sourceLabels(sources: readonly { source: string }[], company?: string | null): string[] {
  return [...new Set(sources.map((s) => sourceLabel(s.source, company)))];
}

const PARSER_LABEL: Record<string, string> = {
  linkedin_digest: "LinkedIn job alert",
  naukri_recommendations: "Naukri recommendations",
  naukri_recruiter_invite: "Naukri recruiter invite",
  ai_assistant_alert: "AI assistant job list",
  gmail_forwarding: "Gmail forwarding confirmation",
};

/** "linkedin_digest@1" → "LinkedIn job alert". Unknown parsers show their name. */
export function parserLabel(parser: string | null | undefined): string {
  if (!parser) return "Not recognised";
  const name = parser.split("@")[0] ?? parser;
  return PARSER_LABEL[name] ?? name;
}

export const MESSAGE_STATUS: Record<string, { label: string; kind: "good" | "warn" | "bad" | "info" }> = {
  accepted: { label: "Reading…", kind: "info" },
  parsed: { label: "Read", kind: "good" },
  unparsed: { label: "Not a job alert", kind: "warn" },
  failed: { label: "Failed", kind: "bad" },
};

export interface JobFilters {
  tab: Tab;
  status: StatusFilter;
  q: string;
  source: "" | "linkedin" | "naukri" | "foundit" | "company" | "adzuna" | "assistant";
  lead: "" | Lead;
  readiness: "" | "ready" | "needs_input";
  range: DateRange;
  from: string; // yyyy-mm-dd, only for range = "custom"
  to: string;
}

export const DEFAULT_FILTERS: JobFilters = { tab: "top", status: "active", q: "", source: "", lead: "", readiness: "", range: "any", from: "", to: "" };

/** yyyy-mm-dd for a local date. */
export function isoDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** The API's from/to for a date range, relative to `today`. */
export function rangeDates(f: Pick<JobFilters, "range" | "from" | "to">, today: Date = new Date()): { from?: string; to?: string } {
  const daysAgo = (n: number) => isoDay(new Date(today.getFullYear(), today.getMonth(), today.getDate() - n));
  switch (f.range) {
    case "today":
      return { from: daysAgo(0) };
    case "7d":
      return { from: daysAgo(6) };
    case "30d":
      return { from: daysAgo(29) };
    case "custom":
      return { ...(f.from ? { from: f.from } : {}), ...(f.to ? { to: f.to } : {}) };
    default:
      return {};
  }
}

/** The query for GET /jobs: empty filters are left out. */
export function jobQuery(f: JobFilters, today: Date = new Date()) {
  const queue = isMatchTab(f.tab)
    ? { tab: f.tab as "top" | "other" | "unscored", status: f.status }
    : { tab: "all" as const, status: f.tab as "applied" | "expired" | "ignored" | "review" | "all" };
  return {
    ...queue,
    ...(f.q.trim() ? { q: f.q.trim() } : {}),
    ...(f.source ? { source: f.source } : {}),
    ...(f.lead ? { lead: f.lead } : {}),
    ...(f.readiness && f.tab === "top" ? { readiness: f.readiness } : {}),
    ...rangeDates(f, today),
  };
}

/** Filters ⇄ the page's URL query, so Back from a job keeps the list as it was. */
export function filtersToSearch(f: JobFilters): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(f) as [keyof JobFilters, string][]) {
    if (v && v !== DEFAULT_FILTERS[k]) p.set(k, v);
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function filtersFromSearch(search: string): JobFilters {
  const p = new URLSearchParams(search);
  const pick = <T extends string>(key: string, allowed: readonly T[], fallback: T): T => {
    const v = p.get(key) as T | null;
    return v && allowed.includes(v) ? v : fallback;
  };
  // Links from before the queues were tabs said ?status=ignored.
  const legacy = p.get("status") === "ignored" ? "ignored" : null;
  return {
    tab: legacy ?? pick("tab", ["top", "other", "unscored", "applied", "expired", "ignored", "all", "review"] as const, "top"),
    status: pick("status", ["active", "new"] as const, "active"),
    q: p.get("q") ?? "",
    source: pick("source", ["", "linkedin", "naukri", "foundit", "company", "adzuna", "assistant"] as const, ""),
    lead: pick("lead", ["", "alert", "recommendation", "recruiter_invite", "company_feed", "job_board"] as const, ""),
    readiness: pick("readiness", ["", "ready", "needs_input"] as const, ""),
    range: pick("range", ["any", "today", "7d", "30d", "custom"] as const, "any"),
    from: /^\d{4}-\d{2}-\d{2}$/.test(p.get("from") ?? "") ? p.get("from")! : "",
    to: /^\d{4}-\d{2}-\d{2}$/.test(p.get("to") ?? "") ? p.get("to")! : "",
  };
}

export type ApplyLink = { href: string; label: string; short: string };

// Where to apply, best first: the company's own careers page, then the portals, then Adzuna (which sends you on to
// the original listing).
const APPLY_ORDER = [...COMPANY_SITES, "linkedin", "naukri", "foundit", "adzuna", "ai_assistant"];

/** True for a Naukri recruiter invite's own apply link, which signs the user in to Naukri. Other jobs' private
 *  apply links (an AI assistant's list gives the employer's careers page) are ordinary public pages. */
export function isNaukriSignInLink(url?: string | null): boolean {
  try {
    return !!url && /(^|\.)naukri\.com$/i.test(new URL(url).hostname);
  } catch {
    return false;
  }
}

/** The link to apply for a job, or null when no listing has a public page. `privateApplyUrl` is the user's own
 *  apply link for the job: shown on the job page only, never in lists. */
export function applyLink(
  sources: readonly { source: string; url?: string | null }[],
  company?: string | null,
  privateApplyUrl?: string | null,
): ApplyLink | null {
  if (isNaukriSignInLink(privateApplyUrl)) return { href: privateApplyUrl!, label: "Apply on Naukri", short: "Apply" };
  const best = sources
    .filter((s) => s.url && APPLY_ORDER.includes(s.source))
    .sort((a, b) => APPLY_ORDER.indexOf(a.source) - APPLY_ORDER.indexOf(b.source))[0];
  if (!best?.url) {
    if (!privateApplyUrl) return null;
    return { href: privateApplyUrl, label: company ? `Apply on ${company}'s site` : "Apply on the employer's site", short: "Apply" };
  }
  if (COMPANY_SITES.includes(best.source)) {
    return { href: best.url, label: company ? `Apply on ${company}'s careers site` : "Apply on the company's careers site", short: "Apply" };
  }
  if (best.source === "adzuna") return { href: best.url, label: "View and apply via Adzuna", short: "Apply" };
  if (best.source === "ai_assistant") {
    return { href: best.url, label: company ? `Apply on ${company}'s site` : "Apply on the employer's site", short: "Apply" };
  }
  return { href: best.url, label: `Apply on ${sourceLabel(best.source)}`, short: "Apply" };
}

/** "Bengaluru · Hybrid · 15-20 Yrs · ₹60-80 L": the facts a card has, in a fixed order. */
export function factsLine(job: { location?: string | null; work_model?: string | null; experience?: string | null; salary?: string | null }): string {
  return [job.location, job.work_model, job.experience, job.salary].filter(Boolean).join(" · ");
}

/** "Today", "Yesterday", "3 days ago", then a date. */
export function seenAgo(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((day(now) - day(d)) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
}

export type Band = "strong" | "good" | "low" | "filtered";

export const BAND: Record<Band, { label: string; kind: "good" | "info" | "warn" | "bad" }> = {
  strong: { label: "Strong match", kind: "good" },
  good: { label: "Good match", kind: "info" },
  low: { label: "Low match", kind: "warn" },
  filtered: { label: "Ruled out", kind: "bad" },
};

export const TABS: { value: Tab; label: string }[] = [
  { value: "top", label: "Top matches" },
  { value: "other", label: "Other jobs" },
  { value: "unscored", label: "Not scored yet" },
  { value: "applied", label: "Applied" },
  { value: "expired", label: "Expired" },
  { value: "ignored", label: "Ignored" },
  { value: "all", label: "All" },
  // Jobs added from Google results with the extension wait here for Keep or Ignore (POC, user 2026-11-17).
  { value: "review", label: "From Google" },
];

/** Does a job with this status still belong in the queue shown? (After Applied/Ignore/Expired it moves.) */
export function inQueue(tab: Tab, status: string): boolean {
  if (tab === "all") return true;
  if (isMatchTab(tab)) return status === "new" || status === "seen";
  return status === tab;
}

export const APPLICATION_STATUS: Record<string, { label: string; kind: "good" | "info" | "warn" | "bad" | "" }> = {
  applied: { label: "Applied", kind: "info" },
  interviewing: { label: "Interviewing", kind: "info" },
  offer: { label: "Offer", kind: "good" },
  accepted: { label: "Accepted", kind: "good" },
  rejected: { label: "Rejected", kind: "bad" },
  withdrawn: { label: "Withdrawn", kind: "" },
  no_response: { label: "No response", kind: "" },
};

/** The from/to (yyyy-mm-dd) for a whole year or one month of it. */
export function periodRange(year: number, month?: number): { from: string; to: string } {
  if (!month) return { from: `${year}-01-01`, to: `${year}-12-31` };
  const last = new Date(year, month, 0).getDate();
  const m = String(month).padStart(2, "0");
  return { from: `${year}-${m}-01`, to: `${year}-${m}-${String(last).padStart(2, "0")}` };
}

/**
 * What a job card says under its score: the primary resume's %, and which resume fits better when it isn't
 * the primary. "Primary resume 82%" or "Primary resume 74% · Cloud and AI fits better (88%)".
 */
export function matchLine(m: {
  score: number;
  primary_score: number | null;
  best_resume_label: string | null;
  best_is_primary: boolean;
}): string {
  const primary = m.primary_score === null ? "" : `Primary resume ${m.primary_score}%`;
  if (m.best_is_primary || !m.best_resume_label) return primary;
  const better = `${m.best_resume_label} fits better (${m.score}%)`;
  return primary ? `${primary} · ${better}` : better;
}

/** Base64 of a file's bytes, for POST /inbox/upload. */
export function toBase64(bytes: Uint8Array): string {
  let s = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) s += String.fromCharCode(...bytes.subarray(i, i + chunk));
  return btoa(s);
}

/** Why a job isn't confirmed yet (catalog `verified` false), or null when it is. A portal, company feed or API
 * listing of the same job confirms it later. */
export function unverifiedNote(job: { verified: boolean; sources: readonly { source: string }[] }): string | null {
  if (job.verified) return null;
  return job.sources.some((s) => s.source === "ai_assistant")
    ? "Found by your AI assistant and not confirmed by a job portal or the company's feed yet. Assistants can get details wrong or list a job that has closed: check it on the employer's page before you apply."
    : "Added by hand (a job you added or an email you forwarded yourself), so BrewMyJob couldn't confirm it with the portal. Check the details on the job's page before you apply.";
}
