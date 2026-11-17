import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

// Milestone 14.4–14.5: the extension's filler (apps/extension/src/fill.js) in a real browser, on forms shaped like
// Greenhouse's and Workday's. These are hand-made pages: real Workday pages saved by the user (docs/milestones.md,
// 14.5) should replace the Workday one.
const SRC = path.resolve(__dirname, "../../extension/src");

const DATA = {
  fields: {
    first_name: "Priya",
    last_name: "Nair",
    full_name: "Priya Nair",
    email: "priya@example.com",
    phone: "+91 90000 00001",
    city: "Bengaluru",
    postal_code: "560001",
    country: "India",
    linkedin: "https://www.linkedin.com/in/priya",
    current_company: "Example Fintech",
  },
  work_history: [
    { title: "VP, Engineering", company: "Example Fintech", start: "2021-01", current: true, description: "Built the AI platform." },
    { title: "Director, Engineering", company: "Sample Retail Tech", start: "2015-03", end: "2020-12", current: false },
  ],
  education: [{ school: "Example Institute of Technology", degree: "B.Tech", start_year: 2000, end_year: 2004 }],
  languages: [],
  answers: [
    { key: "notice_period", question: "What is your notice period?", answer: "60 days" },
    { key: "sponsorship", question: "Will you now or in the future require sponsorship for an employment visa?", answer: "No" },
    { key: "confidentiality", question: "Do you agree not to disclose confidential information of others?", answer: "Yes, I agree" },
    // Voluntary, saved by the user: filled only for the question with this key (user, 2026-11-16).
    { key: "gender", question: "Gender (voluntary)", answer: "Female" },
  ],
  documents: [],
  job: null,
};
const RESUME = { name: "Priya-Nair.pdf", type: "application/pdf", base64: Buffer.from("%PDF-1.4 test").toString("base64") };

async function fill(page: Page, html: string) {
  await page.setContent(html);
  await page.addScriptTag({ path: path.join(SRC, "match.js") });
  await page.addScriptTag({ path: path.join(SRC, "fill.js") });
  return page.evaluate(
    ([d, r]) => (globalThis as unknown as { BrewMyJobFill: { run: (d: unknown, f: unknown) => Promise<unknown> } }).BrewMyJobFill.run(d, { resume: r }),
    [DATA, RESUME] as const,
  ) as Promise<{ filled: number; needs: string[]; skipped: string[] }>;
}

test("fills a Greenhouse-style form by its labels, never the sensitive or unknown questions", async ({ page }) => {
  const report = await fill(
    page,
    `<form>
      <div class="field"><label for="first_name">First Name *</label><input id="first_name" required></div>
      <div class="field"><label for="last_name">Last Name *</label><input id="last_name" required></div>
      <div class="field"><label for="email">Email *</label><input id="email" type="email" required></div>
      <div class="field"><label for="phone">Phone</label><input id="phone" value="+1 555"></div>
      <div class="field"><label for="resume">Resume/CV</label><input id="resume" type="file"></div>
      <div class="field"><label for="li">LinkedIn Profile</label><input id="li"></div>
      <div class="field"><label for="np">Notice period (days)</label><input id="np"></div>
      <div class="field"><label for="country">Country</label>
        <select id="country"><option value="">Select…</option><option value="IN">India</option><option value="US">United States</option></select></div>
      <div class="field"><label for="why">Why do you want to join us?</label><textarea id="why" required></textarea></div>
      <div class="field"><label for="sp">*Will you now or in the future require sponsorship for an employment visa for the country in which this job is located?</label>
        <select id="sp"><option value="">Please Select</option><option value="y">Yes</option><option value="n">No</option></select></div>
      <div class="field"><label for="nda">*I agree that I will not disclose or use any confidential or proprietary information of others, including any former employer.</label>
        <select id="nda"><option value="">Please Select</option><option value="1">Yes, I agree.</option><option value="2">No, I do not agree.</option></select></div>
      <div class="field"><label for="gender">Gender</label><select id="gender"><option value="">Decline</option><option>Female</option></select></div>
      <div class="field"><label for="dis">Disability status</label><select id="dis"><option value="">Decline</option><option>No</option></select></div>
      <button type="submit">Submit application</button>
    </form>`,
  );
  await expect(page.locator("#first_name")).toHaveValue("Priya");
  await expect(page.locator("#last_name")).toHaveValue("Nair");
  await expect(page.locator("#email")).toHaveValue("priya@example.com");
  await expect(page.locator("#phone")).toHaveValue("+1 555"); // already filled: left as it was
  await expect(page.locator("#li")).toHaveValue("https://www.linkedin.com/in/priya");
  await expect(page.locator("#np")).toHaveValue("60 days");
  await expect(page.locator("#country")).toHaveValue("IN");
  await expect(page.locator("#sp")).toHaveValue("n");
  await expect(page.locator("#nda")).toHaveValue("1");
  await expect(page.locator("#why")).toHaveValue("");
  await expect(page.locator("#why")).toHaveAttribute("data-brewmyjob", "needs-you");
  await expect(page.locator("#gender")).toHaveValue("Female"); // the answer the user saved for it
  await expect(page.locator("#dis")).toHaveValue("");
  expect(await page.locator("#resume").evaluate((el: HTMLInputElement) => el.files?.[0]?.name)).toBe("Priya-Nair.pdf");
  expect(report.needs).toEqual(["Why do you want to join us?"]);
  expect(report.skipped).toEqual(["Disability status"]);
  await expect(page.locator("#brewmyjob-toast")).toContainText("click Next or Submit yourself");
});

test("fills a Workday-style page: its field ids, a dropdown, and work experience with Add", async ({ page }) => {
  await page.route("**/*", (r) => r.fulfill({ body: "<html></html>", contentType: "text/html" }));
  await page.goto("https://acme.wd1.myworkdayjobs.com/en-US/careers/job/apply");
  const report = await fill(
    page,
    `<div data-automation-id="formField-legalNameSection_firstName"><label>Given Name(s)</label>
       <input data-automation-id="legalNameSection_firstName"></div>
     <div data-automation-id="formField-legalNameSection_lastName"><label>Family Name</label>
       <input data-automation-id="legalNameSection_lastName"></div>
     <div data-automation-id="formField-addressSection_city"><label>City</label><input data-automation-id="addressSection_city"></div>
     <div data-automation-id="formField-countryDropdown"><label>Country</label>
       <button data-automation-id="countryDropdown" aria-haspopup="listbox"
         onclick="document.getElementById('lb').hidden=false">Select One</button></div>
     <ul id="lb" role="listbox" hidden>
       <li role="option" onclick="document.querySelector('[data-automation-id=countryDropdown]').textContent='India'">India</li>
       <li role="option">Indonesia</li></ul>
     <div data-automation-id="workExperienceSection" id="work">
       <div role="group">
         <div data-automation-id="formField-jobTitle"><label>Job Title</label><input data-automation-id="jobTitle"></div>
         <div data-automation-id="formField-company"><label>Company</label><input data-automation-id="company"></div>
         <input type="checkbox" data-automation-id="currentlyWorkHere">
         <div data-automation-id="startDate"><input data-automation-id="dateSectionMonth-input"><input data-automation-id="dateSectionYear-input"></div>
       </div>
       <button data-automation-id="Add" onclick="
         const g = this.parentElement.querySelector('[role=group]').cloneNode(true);
         g.querySelectorAll('input').forEach(i => { i.value=''; i.checked=false; i.removeAttribute('data-brewmyjob'); i.style.outline=''; });
         this.before(g);">Add</button>
     </div>
     <div data-automation-id="formField-race"><label>Race/Ethnicity</label><input id="race"></div>`,
  );
  await expect(page.locator("[data-automation-id=legalNameSection_firstName]")).toHaveValue("Priya");
  await expect(page.locator("[data-automation-id=legalNameSection_lastName]")).toHaveValue("Nair");
  await expect(page.locator("[data-automation-id=addressSection_city]")).toHaveValue("Bengaluru");
  await expect(page.locator("[data-automation-id=countryDropdown]")).toHaveText("India");
  const titles = page.locator("#work [data-automation-id=jobTitle]");
  await expect(titles).toHaveCount(2);
  await expect(titles.nth(0)).toHaveValue("VP, Engineering");
  await expect(titles.nth(1)).toHaveValue("Director, Engineering");
  await expect(page.locator("#work [data-automation-id=currentlyWorkHere]").first()).toBeChecked();
  await expect(page.locator("#work [data-automation-id=dateSectionYear-input]").nth(1)).toHaveValue("2015");
  await expect(page.locator("#race")).toHaveValue("");
  expect(report.skipped).toContain("Race/Ethnicity");
});

test("fills Workday's newer page by its numbered headings: Work Experience 1, 2 and Education 1", async ({ page }) => {
  // The layout of a real Workday form (2026-11-10): no field ids, a heading per block, labels with "*".
  await page.route("**/*", (r) => r.fulfill({ body: "<html><body></body></html>", contentType: "text/html" }));
  await page.goto("https://acme.wd102.myworkdayjobs.com/en-GB/acme/job/apply");
  const block = (n: number) =>
    `<div role="group"><h4>Work Experience ${n}</h4>
       <label for="w${n}t">Job Title<abbr>*</abbr></label><input id="w${n}t" aria-required="true">
       <label for="w${n}c">Company<abbr>*</abbr></label><input id="w${n}c" aria-required="true">
       <label for="w${n}l">Location<abbr>*</abbr></label><input id="w${n}l" aria-required="true">
       <label for="w${n}n">I currently work here</label><input type="checkbox" id="w${n}n">
       <div data-automation-id="formField-startDate"><label>From<abbr>*</abbr></label>
         <input id="w${n}m" data-automation-id="dateSectionMonth-input"><input id="w${n}y" data-automation-id="dateSectionYear-input"></div>
       <label for="w${n}d">Role Description</label><textarea id="w${n}d"></textarea></div>`;
  const report = await fill(
    page,
    `<h3>My Experience</h3>${block(1)}${block(2)}
     <div role="group"><h4>Education 1</h4>
       <label for="e1s">School or University<abbr>*</abbr></label><input id="e1s" aria-required="true"></div>
     <h3>Websites</h3><label for="u">URL</label><input id="u">`,
  );
  await expect(page.locator("#w1t")).toHaveValue("VP, Engineering");
  await expect(page.locator("#w1c")).toHaveValue("Example Fintech");
  await expect(page.locator("#w1n")).toBeChecked();
  await expect(page.locator("#w2t")).toHaveValue("Director, Engineering");
  await expect(page.locator("#w2c")).toHaveValue("Sample Retail Tech");
  await expect(page.locator("#w2n")).not.toBeChecked();
  await expect(page.locator("#w1m")).toHaveValue("01");
  await expect(page.locator("#w1y")).toHaveValue("2021");
  await expect(page.locator("#w2y")).toHaveValue("2015");
  await expect(page.locator("#w1d")).toHaveValue("Built the AI platform.");
  await expect(page.locator("#e1s")).toHaveValue("Example Institute of Technology");
  // The profile has no location for these roles: amber, never another value.
  await expect(page.locator("#w1l")).toHaveValue("");
  expect(report.needs).toContain("Location*");
});

test("on a Workday page its own resume autofill filled, matches each block to the role by its company", async ({ page }) => {
  // A real JioStar form (2026-11-10): headings in plain divs, Company already filled by Workday's "Autofill with
  // resume" in its own order, one "MM/YYYY" box per date, a required Role Description.
  await page.route("**/*", (r) => r.fulfill({ body: "<html><body></body></html>", contentType: "text/html" }));
  await page.goto("https://acme.wd102.myworkdayjobs.com/en-GB/acme/job/apply");
  const block = (n: number, company: string) =>
    `<div><div class="title">Work Experience ${n}</div>
       <label for="c${n}">Company<abbr>*</abbr></label><input id="c${n}" value="${company}">
       <label for="n${n}">I currently work here</label><input type="checkbox" id="n${n}">
       <label for="f${n}">From<abbr>*</abbr></label><input id="f${n}" placeholder="MM/YYYY">
       <label for="t${n}">To<abbr>*</abbr></label><input id="t${n}" placeholder="MM/YYYY">
       <label for="d${n}">Role Description<abbr>*</abbr></label><textarea id="d${n}" aria-required="true"></textarea></div>`;
  const report = await fill(
    page,
    `${block(1, "Sample Retail Tech Pvt Ltd")}${block(2, "Example Fintech")}${block(3, "Somewhere Else Inc")}`,
  );
  // Block 1 holds the second role (by its company), block 2 the first.
  await expect(page.locator("#f1")).toHaveValue("03/2015");
  await expect(page.locator("#t1")).toHaveValue("12/2020");
  await expect(page.locator("#n1")).not.toBeChecked();
  await expect(page.locator("#f2")).toHaveValue("01/2021");
  await expect(page.locator("#t2")).toHaveValue("");
  await expect(page.locator("#n2")).toBeChecked();
  await expect(page.locator("#d2")).toHaveValue("Built the AI platform.");
  // A role BrewMyJob doesn't know is left to the user, never given another role's facts.
  await expect(page.locator("#f3")).toHaveValue("");
  await expect(page.locator("#d3")).toHaveValue("");
  expect(report.needs).toContain("Role Description*");
});

test("refuses to fill on a job portal", async ({ page }) => {
  await page.route("**/*", (r) => r.fulfill({ body: "<html><body><input id='x'></body></html>", contentType: "text/html" }));
  await page.goto("https://www.linkedin.com/jobs/view/1");
  await page.addScriptTag({ path: path.join(SRC, "match.js") });
  await page.addScriptTag({ path: path.join(SRC, "fill.js") });
  const error = await page.evaluate(() =>
    (globalThis as unknown as { BrewMyJobFill: { run: (d: unknown) => Promise<unknown> } }).BrewMyJobFill.run({ fields: {}, answers: [] })
      .then(() => null, (e: Error) => e.message),
  );
  expect(error).toContain("doesn't fill forms on job portals");
  await expect(page.locator("#x")).toHaveValue("");
});
