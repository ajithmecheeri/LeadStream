/** Finding jobs on Google in your own browser (route 1, 2026-11-14). BrewMyJob never opens portal pages. */

export type Window = "day" | "week" | "month";

export const WINDOWS: { value: Window; label: string }[] = [
  { value: "day", label: "Past 24 hours" },
  { value: "week", label: "Past week" },
  { value: "month", label: "Past month" },
];

const TBS: Record<Window, string> = { day: "qdr:d", week: "qdr:w", month: "qdr:m" };

/** A Google search link for the query, limited to pages from the chosen period. */
export function googleUrl(query: string, window: Window): string {
  const params = new URLSearchParams({ q: query, tbs: TBS[window] });
  return `https://www.google.com/search?${params.toString()}`;
}

const SMALL = new Set(["of", "and", "the", "for", "in", "at", "to", "a", "an", "on", "with"]);
const UPPER = new Set(["vp", "cto", "cio", "ceo", "ai", "ml", "it", "qa", "hr", "ui", "ux", "sre", "avp", "svp", "evp", "gm"]);

function titleCase(words: string[]): string {
  return words
    .map((w, i) => (UPPER.has(w) ? w.toUpperCase() : i > 0 && SMALL.has(w) ? w : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");
}

/**
 * The title and company a LinkedIn job link spells out ("…/jobs/view/head-of-engineering-at-acme-4490581539"),
 * as a starting point for the form; read from the link only. Other links give nothing.
 */
export function guessFromLink(url: string): { title: string; company: string } | null {
  let path: string;
  try {
    const u = new URL(url.trim());
    if (!/(^|\.)linkedin\.com$/i.test(u.hostname)) return null;
    path = decodeURIComponent(u.pathname);
  } catch {
    return null;
  }
  const m = /\/jobs\/view\/([a-z0-9-]+?)-\d{6,}\/?$/i.exec(path);
  if (!m) return null;
  const words = m[1]!.toLowerCase().split("-").filter(Boolean);
  const at = words.lastIndexOf("at");
  if (at <= 0 || at === words.length - 1) return null;
  return { title: titleCase(words.slice(0, at)), company: titleCase(words.slice(at + 1)) };
}
