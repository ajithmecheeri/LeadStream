import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const EMAILS = path.resolve(__dirname, "../../../backend/tests/fixtures/emails");
const LINKEDIN = path.join(EMAILS, "linkedin-alert-vice-president-bangalore-2026-10-29.eml");
const NAUKRI = path.join(EMAILS, "naukri-alert-recommended-jobs-2026-09-21.eml");

// A fictional resume (the same person as the backend's tests/samples.py).
const RESUME = `PRIYA NAIR
VP, ENGINEERING | CLOUD AND AI PLATFORMS
+91 90000 00001 | priya.nair@example.com | linkedin.com/in/priya-nair-example | Bengaluru, India
PROFESSIONAL SUMMARY
Engineering leader with 21+ years building cloud-native SaaS platforms for banking and retail clients.
Led GenAI and LLM product features, AWS and Azure migrations, and teams of 80 engineers.
CORE COMPETENCIES
Product Development | Microservices | Kubernetes
Generative AI (LLMs, RAG) | AWS / Azure | Agile Delivery
PROFESSIONAL EXPERIENCE
VP, Engineering | Example Fintech Pvt Ltd - Bengaluru\tJan 2021 - Present
Built an AI platform on AWS with LLM-based document processing for lending.
Director, Engineering | Sample Retail Tech - Bengaluru\tMar 2015 - Dec 2020
Senior Software Engineer | Demo Systems\tJun 2004 - Feb 2015
TECHNICAL SKILLS
Cloud & DevOps: AWS, Azure, Docker, Kubernetes, Terraform
AI: LLMs, RAG, Machine Learning
EDUCATION
B.Tech, Computer Science\t2000 - 2004
`;

const DELIVERY = `Programme director with 21 years running regulatory reporting and finance transformation
programmes for banks: budgets, vendors, stakeholders and delivery governance across three countries.`;

const LETTER = `Dear Hiring Manager,
I lead engineering teams that build cloud and AI platforms for banks and retailers, and I would welcome the
chance to talk about the role. Regards, Priya`;

async function signUp(page: Page) {
  await page.goto("/sign-up");
  await page.getByLabel("First name", { exact: true }).fill("Priya");
  await page.getByLabel("Last name", { exact: true }).fill("Nair");
  await page.getByLabel("Email", { exact: true }).fill(`e2e-match-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Re-enter password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Where do you want to work?").fill("Bengaluru, Remote");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Priya" })).toBeVisible();
}

// Needs `make up` (ENV=local, worker running). Scoring runs in the worker; with VOYAGE_API_KEY set it also
// calls Voyage, so the test checks the shape of the result, not exact percentages.
test("a resume scores every job: tabs, match %, suggested resume and cover letter", async ({ page }) => {
  test.setTimeout(180_000);
  const nav = page.getByRole("navigation", { name: "Main" });
  await signUp(page);

  // Two alert emails: 17 jobs, not scored until there is a resume.
  await nav.getByRole("link", { name: "Inbox", exact: true }).click();
  await page.getByTestId("eml-input").setInputFiles([LINKEDIN, NAUKRI]);
  await expect(page.getByTestId("inbox-row").filter({ hasText: "Read" })).toHaveCount(2, { timeout: 30_000 });
  await nav.getByRole("link", { name: "Jobs", exact: true }).click();
  await expect(page.getByText("Add your resume to see match scores")).toBeVisible();

  // Upload a resume on the Profile page; it becomes the primary one.
  await nav.getByRole("link", { name: "Profile", exact: true }).click();
  await page.getByTestId("resume-input").setInputFiles({ name: "Priya_Nair_Resume.txt", mimeType: "text/plain", buffer: Buffer.from(RESUME) });
  await expect(page.getByText("1 resume added.")).toBeVisible();
  const item = page.getByTestId("resume-item");
  await expect(item).toHaveCount(1);
  await expect(item).toContainText("Priya Nair Resume");
  await expect(item).toContainText("Primary");

  // Fill the profile from it, review and save.
  await page.getByRole("button", { name: "Fill profile from Priya Nair Resume" }).click();
  await expect(page.getByText("Filled from “Priya Nair Resume”")).toBeVisible();
  await expect(page.getByLabel("Headline")).toHaveValue("VP, Engineering | Cloud And AI Platforms");
  await expect(page.getByLabel("Years of experience")).toHaveValue("21");
  await expect(page.getByLabel("Current location")).toHaveValue("Bengaluru");
  await page.getByRole("button", { name: "Save profile" }).click();
  await expect(page.getByText("Profile saved.")).toBeVisible();

  // A cover letter, pasted.
  const letters = page.getByTestId("letter-library");
  await letters.getByRole("button", { name: "Paste text" }).click();
  await letters.getByLabel("cover letter name").fill("Tech leadership");
  await letters.getByLabel("cover letter text").fill(LETTER);
  await letters.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("letter-item")).toContainText("Default");

  // Jobs: the worker scores them; top matches come first with the primary resume's %.
  await nav.getByRole("link", { name: "Jobs", exact: true }).click();
  const tabs = page.getByRole("group", { name: "Queue" });
  const first = page.getByTestId("job-card").first();
  await expect(first.getByTestId("match-score")).toBeVisible({ timeout: 90_000 });
  await expect(first.getByTestId("match-line")).toContainText("Primary resume");
  const scores = await page.getByTestId("match-score").allTextContents();
  const nums = scores.map((s) => Number(s.replace("%", "")));
  expect(nums).toEqual([...nums].sort((a, b) => b - a));
  expect(Math.min(...nums)).toBeGreaterThanOrEqual(70);

  // Finance and supply-chain roles are in Other jobs, below the top matches.
  await tabs.getByRole("button", { name: /^Other jobs/ }).click();
  await expect(page.getByTestId("job-card").filter({ hasText: "SEG & India CFO" })).toBeVisible();
  await expect(page.getByTestId("job-card").filter({ hasText: "Head S&OP/SIOP" })).toBeVisible();

  // A job's page suggests the resume and the cover letter.
  // Open Top matches fresh (clicking the tab and the first card at once could still hit the old list).
  await page.goto("/jobs");
  const best = page.getByTestId("job-card").first();
  await expect(best.getByTestId("readiness")).toBeVisible();
  await best.getByRole("link").first().click();
  const panel = page.getByTestId("match-panel");
  await expect(panel.getByTestId("match-score")).toBeVisible();
  await expect(panel.getByTestId("skills-check")).toBeVisible();  // always shown, highlighted when skills are missing
  await expect(panel.getByTestId("suggested-resume")).toContainText("Priya Nair Resume");
  // The rescore that picks up the cover letter may land after the page loads: reload until it has.
  await expect(async () => {
    if (!(await panel.getByTestId("suggested-cover-letter").textContent())?.includes("Tech leadership")) await page.reload();
    await expect(panel.getByTestId("suggested-cover-letter")).toContainText("Tech leadership", { timeout: 3_000 });
  }).toPass({ timeout: 60_000 });
  await panel.getByText("Show").click();
  await expect(panel.getByTestId("suggested-cover-letter")).toContainText("I lead engineering teams");

  // Readiness: a new user's top match needs input; answering a question here clears it on every job.
  const readiness = page.getByTestId("todo-panel");
  await expect(readiness.getByTestId("readiness-status")).toContainText("Needs your input");
  // (Not a to-do count: a background rescore can change the job's other to-dos meanwhile.)
  await readiness.getByLabel("Answer: What is your notice period?").fill("90 days");
  await readiness.getByRole("button", { name: "Save answer" }).first().click();
  await expect(readiness.getByText("What is your notice period?")).toHaveCount(0);

  // The answer is in the answer bank, where the other common questions wait.
  await nav.getByRole("link", { name: "Profile", exact: true }).click();
  await page.getByTestId("tab-answers").click();
  const notice = page.getByTestId("answer-row").filter({ hasText: "What is your notice period?" });
  await expect(notice.getByTestId("answer-text")).toHaveText("90 days");
  await page.getByRole("button", { name: "Answer: What is your expected CTC?" }).click();
  await page.getByLabel("Answer: What is your expected CTC?").fill("1.2 Cr");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByTestId("answer-row").filter({ hasText: "expected CTC" }).getByTestId("answer-text")).toHaveText("1.2 Cr");
  await nav.getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(page.getByTestId("needs-input")).toContainText("need your input");
  await page.goBack();
  await page.goBack();

  // A second resume (a variation): every job then shows both, the primary marked.
  await nav.getByRole("link", { name: "Profile", exact: true }).click();
  const resumes = page.getByTestId("resume-library");
  await resumes.getByRole("button", { name: "Paste text" }).click();
  await resumes.getByLabel("resume name").fill("Delivery");
  await resumes.getByLabel("resume text").fill(DELIVERY);
  await resumes.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("resume-item")).toHaveCount(2);
  await page.goBack();
  await expect(async () => {
    await page.reload();
    await expect(page.getByTestId("resume-ranking")).toContainText("Delivery", { timeout: 2_000 });
  }).toPass({ timeout: 60_000 });
  await expect(page.getByTestId("resume-ranking")).toContainText("Primary");

  // Compare the other resume with the suggested one, factor by factor.
  await panel.getByRole("button", { name: /^Compare .* with the suggested resume$/ }).click();
  const compare = panel.getByTestId("resume-compare");
  await expect(compare.getByTestId("compare-score")).toHaveText(/^\d+%$/);
  await expect(compare.getByRole("row")).not.toHaveCount(0);
});
