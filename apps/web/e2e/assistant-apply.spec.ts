import path from "node:path";
import { expect, test } from "@playwright/test";

// User feedback 2026-11-11: three jobs from an AI assistant's email ("Official application:" links) came in
// without an Apply button. Every job from that email must have one, on the list and on the job page.
const EMAILS = path.resolve(__dirname, "../../../backend/tests/fixtures/emails");
const ASSISTANT = path.join(EMAILS, "ai-assistant-chatgpt-leadership-bengaluru-2026-11-11.eml");
const SENDER = "candidate@example.com"; // the fixture's From: the user's own address, listed on Mail setup

const JOBS = [
  { title: "Director - Delivery Data & AI", company: "Thoughtworks", href: "https://www.thoughtworks.com/en-in/careers/jobs/8376818" },
  { title: "Engineering Director", company: "Hitachi Vantara", href: "https://careers.hitachi.com/engineering-director/job/R0150236" },
  {
    title: "Sr. Director, Technology BU Interface",
    company: "Johnson & Johnson / DePuy Synthes",
    href: "https://jj.wd5.myworkdayjobs.com/JJ/job/Bangalore-Karnataka-India/a-Sr-Director--Technology-BU-Interface---International--Orthopaedics-_R-100161-1",
  },
];

// Needs the stack with ENV=local (`make up` or `make dev`) and the worker running.
test("every job from an AI assistant's email has an Apply button to the employer's site", async ({ page }) => {
  test.setTimeout(90_000);
  const nav = page.getByRole("navigation", { name: "Main" });

  await page.goto("/sign-up");
  await page.getByLabel("First name", { exact: true }).fill("Apply");
  await page.getByLabel("Last name", { exact: true }).fill("Tester");
  await page.getByLabel("Email", { exact: true }).fill(`e2e-assistant-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Re-enter password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Where do you want to work?").fill("Bengaluru, Remote");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Apply" })).toBeVisible();

  // The assistant mails from the user's own address, so that address is listed first.
  await nav.getByRole("link", { name: "Mail setup", exact: true }).click();
  const byHand = page.getByTestId("forward-by-hand");
  await byHand.getByLabel("Address you forward from").fill(SENDER);
  await byHand.getByRole("button", { name: "Add address" }).click();
  await expect(byHand.getByTestId("forward-sender")).toHaveText(new RegExp(SENDER.replace(".", "\\.")));

  await nav.getByRole("link", { name: "Inbox", exact: true }).click();
  await page.getByTestId("eml-input").setInputFiles(ASSISTANT);
  // "Read", not "Reading…": the worker has finished with it.
  await expect(page.getByTestId("inbox-row")).toContainText(/Read(?!ing)/, { timeout: 30_000 });

  await nav.getByRole("link", { name: "Jobs", exact: true }).click();
  await page.getByRole("group", { name: "Queue" }).getByRole("button", { name: /^All/ }).click();
  await expect(page.getByTestId("jobs-total")).toHaveText("3 jobs");
  for (const job of JOBS) {
    const card = page.getByTestId("job-card").filter({ hasText: job.title });
    await expect(card.getByTestId("apply-link")).toHaveAttribute("href", job.href);
  }

  // On the job page it names the employer, not a job portal.
  await page.getByTestId("job-card").filter({ hasText: JOBS[0].title }).getByRole("link", { name: JOBS[0].title }).click();
  await expect(page.getByRole("heading", { level: 1, name: JOBS[0].title })).toBeVisible();
  const apply = page.getByTestId("apply-link");
  await expect(apply).toHaveText(`Apply on ${JOBS[0].company}'s site ↗`);
  await expect(apply).toHaveAttribute("href", JOBS[0].href);

  // The BrewMyJob name at the top left goes to the home page (user feedback 2026-11-11).
  await page.getByTestId("brand-home").click();
  await expect(page).toHaveURL(/\/$/);
});
