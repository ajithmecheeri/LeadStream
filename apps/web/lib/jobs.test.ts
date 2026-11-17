import { describe, expect, it } from "vitest";
import {
  isNaukriSignInLink,
  applyLink,
  DEFAULT_FILTERS,
  factsLine,
  filtersFromSearch,
  filtersToSearch,
  inQueue,
  jobQuery,
  matchLine,
  parserLabel,
  periodRange,
  rangeDates,
  seenAgo,
  sourceLabels,
  toBase64,
  unverifiedNote,
} from "./jobs";

const TODAY = new Date(2026, 9, 31, 15, 0); // 31 Oct 2026, local time

describe("rangeDates", () => {
  it("counts today as day one of a range", () => {
    expect(rangeDates({ range: "today", from: "", to: "" }, TODAY)).toEqual({ from: "2026-10-31" });
    expect(rangeDates({ range: "7d", from: "", to: "" }, TODAY)).toEqual({ from: "2026-10-25" });
    expect(rangeDates({ range: "30d", from: "", to: "" }, TODAY)).toEqual({ from: "2026-10-02" });
  });

  it("uses the custom dates as given and leaves out empty ones", () => {
    expect(rangeDates({ range: "custom", from: "2026-10-01", to: "" }, TODAY)).toEqual({ from: "2026-10-01" });
    expect(rangeDates({ range: "any", from: "2026-10-01", to: "2026-10-02" }, TODAY)).toEqual({});
  });
});

describe("jobQuery", () => {
  it("sends only the filters that are set", () => {
    expect(jobQuery(DEFAULT_FILTERS, TODAY)).toEqual({ tab: "top", status: "active" });
    expect(jobQuery({ ...DEFAULT_FILTERS, q: "  cto ", source: "naukri", lead: "recruiter_invite", range: "today" }, TODAY)).toEqual({
      tab: "top",
      status: "active",
      q: "cto",
      source: "naukri",
      lead: "recruiter_invite",
      from: "2026-10-31",
    });
  });
});

describe("filters in the URL", () => {
  it("round-trips and omits defaults", () => {
    const f = { ...DEFAULT_FILTERS, status: "new" as const, q: "vp eng", range: "custom" as const, from: "2026-10-01" };
    const s = filtersToSearch(f);
    expect(s).toBe("?status=new&q=vp+eng&range=custom&from=2026-10-01");
    expect(filtersFromSearch(s)).toEqual(f);
    expect(filtersToSearch(DEFAULT_FILTERS)).toBe("");
  });

  it("ignores values it doesn't know", () => {
    expect(filtersFromSearch("?status=sent&source=indeed&from=yesterday")).toEqual(DEFAULT_FILTERS);
  });
});

describe("labels", () => {
  it("names parsers and keeps unknown ones readable", () => {
    expect(parserLabel("linkedin_digest@1")).toBe("LinkedIn job alert");
    expect(parserLabel("something_new@2")).toBe("something_new");
    expect(parserLabel(null)).toBe("Not recognised");
  });

  it("joins the facts a job has", () => {
    expect(factsLine({ location: "Bengaluru", work_model: null, experience: "15-20 Yrs", salary: "" })).toBe("Bengaluru · 15-20 Yrs");
  });

  it("says when a job was first seen", () => {
    expect(seenAgo(new Date(2026, 9, 31, 1).toISOString(), TODAY)).toBe("Today");
    expect(seenAgo(new Date(2026, 9, 30, 23).toISOString(), TODAY)).toBe("Yesterday");
    expect(seenAgo(new Date(2026, 9, 27).toISOString(), TODAY)).toBe("4 days ago");
    expect(seenAgo(new Date(2026, 8, 2).toISOString(), TODAY)).toBe("2 Sept");
  });
});

describe("toBase64", () => {
  it("encodes bytes, including large files", () => {
    expect(toBase64(new TextEncoder().encode("From: a@b\r\n"))).toBe("RnJvbTogYUBiDQo=");
    const big = new Uint8Array(100_000).fill(65);
    expect(atob(toBase64(big)).length).toBe(100_000);
  });
});

describe("match line", () => {
  const m = { score: 88, primary_score: 74, best_resume_label: "Cloud and AI", best_is_primary: false };
  it("names a better variation next to the primary's score", () => {
    expect(matchLine(m)).toBe("Primary resume 74% · Cloud and AI fits better (88%)");
  });
  it("shows only the primary when it is the best", () => {
    expect(matchLine({ ...m, primary_score: 88, best_is_primary: true })).toBe("Primary resume 88%");
  });
});

describe("tabs in the URL", () => {
  it("defaults to top matches and keeps other tabs", () => {
    expect(filtersFromSearch("").tab).toBe("top");
    expect(filtersToSearch({ ...DEFAULT_FILTERS, tab: "other" })).toBe("?tab=other");
    expect(filtersFromSearch("?tab=other").tab).toBe("other");
    expect(filtersFromSearch("?tab=best").tab).toBe("top");
  });
});

describe("readiness filter", () => {
  it("is sent and kept in the URL", () => {
    const f = { ...DEFAULT_FILTERS, readiness: "needs_input" as const };
    expect(jobQuery(f, TODAY)).toEqual({ tab: "top", status: "active", readiness: "needs_input" });
    expect(filtersFromSearch(filtersToSearch(f))).toEqual(f);
    expect(filtersFromSearch("?readiness=soon").readiness).toBe("");
  });
});

describe("queues", () => {
  it("sends Applied, Expired and Ignored as a status", () => {
    expect(jobQuery({ ...DEFAULT_FILTERS, tab: "applied" }, TODAY)).toEqual({ tab: "all", status: "applied" });
    expect(jobQuery({ ...DEFAULT_FILTERS, tab: "all" }, TODAY)).toEqual({ tab: "all", status: "all" });
    expect(jobQuery({ ...DEFAULT_FILTERS, tab: "other", status: "new" }, TODAY)).toEqual({ tab: "other", status: "new" });
    // Readiness belongs to Top matches only.
    expect(jobQuery({ ...DEFAULT_FILTERS, tab: "expired", readiness: "ready" }, TODAY)).toEqual({ tab: "all", status: "expired" });
  });

  it("reads old ?status=ignored links as the Ignored tab", () => {
    expect(filtersFromSearch("?status=ignored").tab).toBe("ignored");
    expect(filtersFromSearch("?tab=applied").tab).toBe("applied");
  });

  it("knows when a job leaves the queue shown", () => {
    expect(inQueue("top", "applied")).toBe(false);
    expect(inQueue("top", "seen")).toBe(true);
    expect(inQueue("ignored", "seen")).toBe(false);
    expect(inQueue("applied", "applied")).toBe(true);
    expect(inQueue("all", "expired")).toBe(true);
  });
});

describe("periodRange", () => {
  it("covers a whole month or year", () => {
    expect(periodRange(2026, 2)).toEqual({ from: "2026-02-01", to: "2026-02-28" });
    expect(periodRange(2028, 2)).toEqual({ from: "2028-02-01", to: "2028-02-29" });
    expect(periodRange(2026)).toEqual({ from: "2026-01-01", to: "2026-12-31" });
  });
});

describe("applyLink", () => {
  const linkedin = { source: "linkedin", url: "https://www.linkedin.com/jobs/view/1" };
  const naukri = { source: "naukri", url: "https://www.naukri.com/job-listings-x-1" };
  const careers = { source: "greenhouse", url: "https://boards.greenhouse.io/acme/jobs/7" };

  it("prefers the company's own careers page", () => {
    expect(applyLink([linkedin, careers, naukri], "Acme")).toEqual({
      href: careers.url,
      label: "Apply on Acme's careers site",
      short: "Apply",
    });
  });
  it("falls back to the portals, LinkedIn first", () => {
    expect(applyLink([naukri, linkedin])?.label).toBe("Apply on LinkedIn");
    expect(applyLink([naukri])?.href).toBe(naukri.url);
    expect(applyLink([{ source: "adzuna", url: "https://www.adzuna.in/land/ad/5" }])?.label).toBe("View and apply via Adzuna");
    expect(applyLink([{ source: "ai_assistant", url: "https://jobs.sap.com/en/jobs/1/" }], "SAP")?.label).toBe("Apply on SAP's site");
    expect(sourceLabels([{ source: "ai_assistant" }])).toEqual(["AI assistant alert"]);
  });
  it("uses a recruiter invite's private link, and has nothing without a public page", () => {
    expect(applyLink([{ source: "naukri_rdx", url: null }], "Acme", "https://www.naukri.com/apply?mid=1")?.label).toBe("Apply on Naukri");
    expect(applyLink([{ source: "naukri_rdx", url: null }])).toBeNull();
  });
  it("labels an AI assistant job's own link as the employer's site, not Naukri", () => {
    const sap = "https://jobs.sap.com/en/jobs/1/";
    expect(applyLink([{ source: "ai_assistant", url: sap }], "SAP", sap)?.label).toBe("Apply on SAP's site");
    expect(applyLink([], null, sap)).toEqual({ href: sap, label: "Apply on the employer's site", short: "Apply" });
    expect(isNaukriSignInLink(sap)).toBe(false);
    expect(isNaukriSignInLink("https://www.naukri.com/apply?mid=1")).toBe(true);
    expect(isNaukriSignInLink("not a url")).toBe(false);
  });
});

describe("sourceLabels", () => {
  it("names portals plainly and company feeds by the company", () => {
    expect(sourceLabels([{ source: "linkedin" }, { source: "naukri" }])).toEqual(["LinkedIn", "Naukri"]);
    expect(sourceLabels([{ source: "naukri_rdx" }])).toEqual(["Naukri recruiter"]);
    expect(sourceLabels([{ source: "greenhouse" }, { source: "linkedin" }], "Okta")).toEqual(["Okta careers site", "LinkedIn"]);
    expect(sourceLabels([{ source: "lever" }])).toEqual(["Company careers site"]);
    expect(sourceLabels([{ source: "adzuna" }])).toEqual(["Adzuna"]);
  });
});

describe("unverifiedNote", () => {
  it("explains unconfirmed jobs by where they came from", () => {
    expect(unverifiedNote({ verified: true, sources: [{ source: "ai_assistant" }] })).toBeNull();
    expect(unverifiedNote({ verified: false, sources: [{ source: "ai_assistant" }] })).toMatch(/AI assistant/);
    expect(unverifiedNote({ verified: false, sources: [{ source: "linkedin" }] })).toMatch(/Added by hand/);
  });
});
