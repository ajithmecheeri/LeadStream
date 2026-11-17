import { beforeAll, describe, expect, it } from "vitest";

// The browser extension's field rules (apps/extension/src/match.js, milestone 14). It's a plain script that sets
// globalThis.BrewMyJobMatch, so it is loaded for its side effect.
type Match = {
  isBlocked: (host: string) => boolean;
  system: (host: string) => string;
  keyFor: (label: string) => string | null;
  isSensitive: (label: string) => boolean;
  answerFor: (label: string, answers: { key: string; question: string; answer: string }[]) => string | null;
  pickOption: (options: { text: string; value: string }[], value: string) => { text: string; value: string } | null;
  fileKind: (label: string) => string | null;
};
let M: Match;

beforeAll(async () => {
  await import("../../extension/src/match.js");
  M = (globalThis as unknown as { BrewMyJobMatch: Match }).BrewMyJobMatch;
});

describe("extension field rules", () => {
  it("never fills job portals, and knows the company application systems", () => {
    for (const host of ["www.linkedin.com", "in.linkedin.com", "www.naukri.com", "in.indeed.com", "www.iimjobs.com"]) {
      expect(M.isBlocked(host)).toBe(true);
    }
    expect(M.isBlocked("boards.greenhouse.io")).toBe(false);
    expect(M.isBlocked("notlinkedin.com")).toBe(false);
    expect(M.system("acme.wd5.myworkdayjobs.com")).toBe("workday");
    expect(M.system("job-boards.greenhouse.io")).toBe("greenhouse");
    expect(M.system("jobs.lever.co")).toBe("lever");
    expect(M.system("jobs.ashbyhq.com")).toBe("ashby");
    expect(M.system("careers.example.com")).toBe("other");
  });

  it("reads what a field asks for from its label", () => {
    const cases: [string, string | null][] = [
      ["First Name*", "first_name"],
      ["Legal last name", "last_name"],
      ["Full name", "full_name"],
      ["Email address", "email"],
      ["Mobile number", "phone"],
      ["Address Line 1", "address_line1"],
      ["Postal Code", "postal_code"],
      ["City", "city"],
      ["LinkedIn Profile", "linkedin"],
      ["Portfolio / GitHub", "website"],
      ["Name of your current employer", "current_company"],
      ["Current CTC (INR)", "current_ctc"],
      ["Expected salary", "expected_ctc"],
      ["What is your notice period?", "notice_period"],
      ["Are you willing to relocate to Pune?", "relocation"],
      // Company forms' Yes/No questions (GE HealthCare on Workday, 2026-11-15).
      ["Are you currently subject to any type of agreement, such as a non-competition or non-solicitation, with another employer that may restrict your ability to perform the job for which you are applying?", "non_compete"],
      ["I agree that I will not disclose or use, while interviewing with or employed with GE HealthCare and GE HealthCare's affiliate businesses, any confidential or proprietary information of others, including any former employer.", "confidentiality"],
      ["Are you legally authorized to work in the country where this job is located?", "legally_authorized"],
      ["Will you now or in the future require sponsorship for an employment visa for the country in which this job is located?", "sponsorship"],
      ["If there is a specific location(s), are you willing to work in that location (not applicable to fully remote roles)?", "work_location"],
      ["Are you younger than 18 years old? Note: this question is used to avoid child labor issues; if you answer Yes, you are otherwise qualified for the role and we decide to move forward, we will ask additional questions to ensure compliance with type of work and hours worked.", "under_18"],
      ["Many countries, including the US, have restrictions on a private industry/government contractor hiring certain former government employees. Were you ever a Government employee (civil service or military) (https://careers.gehealthcare.com/global/en/definition-of-government)?", "former_government"],
      ["Have your immediate family member(s) (spouse, parent, sibling or child) or business partner(s) ever been employed by any Government (https://careers.gehealthcare.com/global/en/definition-of-government)?", "family_government"],
      ["Why do you want to work here?", null],
    ];
    for (const [label, key] of cases) expect([label, M.keyFor(label)]).toEqual([label, key]);
  });

  it("leaves sensitive questions to the user", () => {
    for (const label of ["Race/Ethnicity", "Gender and sexual orientation", "Veteran status", "Disability", "Date of birth", "PAN number"]) {
      expect(M.isSensitive(label)).toBe(true);
      expect(M.keyFor(label)).toBeNull();
    }
    expect(M.isSensitive("Languages you speak")).toBe(false);
  });

  it("fills gender and ethnicity only from the answer saved for them (user, 2026-11-16)", () => {
    expect([M.keyFor("Gender"), M.keyFor("Ethnicity"), M.isSensitive("Gender")]).toEqual(["gender", "ethnicity", false]);
    expect(M.keyFor("Have you served in any of the below India Uniformed forces?")).toBe("uniformed_forces");
    const saved = [{ key: "gender", question: "Gender (voluntary)", answer: "Male" }];
    expect(M.answerFor("Gender", saved)).toBe("Male");
    // No loose match: an answer to some other question worded alike is never used.
    expect(M.answerFor("Ethnicity", [{ key: "my_ethnicity", question: "Ethnicity", answer: "Asian" }])).toBeNull();
  });

  it("matches answer-bank questions by meaning", () => {
    const answers = [
      { key: "notice_period", question: "What is your notice period?", answer: "60 days" },
      { key: "do_you_have_a_valid_passport", question: "Do you have a valid passport?", answer: "Yes" },
      { key: "team_size", question: "How large a team have you managed?", answer: "80 engineers" },
    ];
    expect(M.answerFor("Notice period (days)", answers)).toBe("60 days");
    expect(M.answerFor("How large a team have you managed so far?", answers)).toBe("80 engineers");
    expect(M.answerFor("What size team have you managed?", answers)).toBeNull(); // too loose a match: left blank
    expect(M.answerFor("Do you hold a valid passport?", answers)).toBeNull(); // sensitive: passport
    expect(M.answerFor("Favourite colour", answers)).toBeNull();
  });

  it("picks dropdown options and file fields", () => {
    const options = [
      { text: "Select One", value: "" },
      { text: "India", value: "IN" },
      { text: "Indonesia", value: "ID" },
    ];
    expect(M.pickOption(options, "India")?.value).toBe("IN");
    expect(M.pickOption(options, "in")?.value).toBe("IN");
    expect(M.pickOption(options, "Germany")).toBeNull();
    const agree = [
      { text: "Please Select", value: "" },
      { text: "Yes, I agree.", value: "1" },
      { text: "No, I do not agree.", value: "2" },
    ];
    expect(M.pickOption(agree, "Yes, I agree")?.value).toBe("1");
    const yesNo = [{ text: "Please Select", value: "" }, { text: "Yes", value: "y" }, { text: "No", value: "n" }];
    expect(M.pickOption(yesNo, "No")?.value).toBe("n");
    expect(M.fileKind("Resume/CV")).toBe("resume");
    expect(M.fileKind("Cover Letter")).toBe("cover_letter");
    expect(M.fileKind("Profile photo")).toBeNull();
  });
});

// Every extension script must parse: the background script isn't loaded by any other test, and a syntax error there
// silently stops the extension (2026-11-17: "Adding…" for ever). Module imports are dropped before parsing.
describe("extension scripts", () => {
  it("all parse", async () => {
    const { readdirSync, readFileSync } = await import("node:fs");
    const { join, resolve } = await import("node:path");
    const dir = resolve(__dirname, "../../extension");
    const files = ["popup.js", ...readdirSync(join(dir, "src")).filter((f) => f.endsWith(".js")).map((f) => `src/${f}`)];
    expect(files).toContain("src/background.js");
    for (const f of files) {
      const src = readFileSync(join(dir, f), "utf8").replace(/^import .*$/gm, "");
      expect(() => new Function(`return async () => {\n${src}\n}`), f).not.toThrow();
    }
  });
});
