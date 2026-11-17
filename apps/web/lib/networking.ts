/** Labels and small helpers for the Networking page. Pure functions (unit-tested). */

export type Stage = "sent" | "accepted" | "conversation" | "referral" | "closed";

export const STAGES: { value: Stage; label: string }[] = [
  { value: "sent", label: "Sent" },
  { value: "accepted", label: "Accepted" },
  { value: "conversation", label: "In conversation" },
  { value: "referral", label: "Referred you" },
  { value: "closed", label: "Closed" },
];
export const STAGE_LABEL = Object.fromEntries(STAGES.map((s) => [s.value, s.label])) as Record<Stage, string>;

export const KIND_LABEL: Record<"warm" | "target" | "followup", string> = {
  warm: "Someone you know",
  target: "Someone to find",
  followup: "Follow up",
};

/** "Senior Talent Acquisition Partner · Commonwealth Bank of Australia" */
export function personLine(p: { title?: string | null; company?: string | null }): string {
  return [p.title, p.company].filter(Boolean).join(" · ");
}

/** "3 of 5 done" for the day's list. */
export function progress(items: { status: string }[]): string {
  const done = items.filter((i) => i.status !== "open").length;
  return `${done} of ${items.length} done`;
}
