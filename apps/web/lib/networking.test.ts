import { describe, expect, it } from "vitest";
import { personLine, progress, STAGE_LABEL } from "./networking";

describe("networking labels", () => {
  it("joins what is known about a person", () => {
    expect(personLine({ title: "Staff Engineer", company: "Commonwealth Bank" })).toBe("Staff Engineer · Commonwealth Bank");
    expect(personLine({ title: null, company: "Helix" })).toBe("Helix");
    expect(personLine({})).toBe("");
  });

  it("counts the day's list", () => {
    expect(progress([{ status: "done" }, { status: "skipped" }, { status: "open" }])).toBe("2 of 3 done");
  });

  it("names every stage", () => {
    expect(STAGE_LABEL.referral).toBe("Referred you");
  });
});
