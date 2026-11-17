import path from "node:path";
import { expect, test } from "@playwright/test";

// A real (sanitised) LinkedIn alert with six jobs, and a Naukri recommendations email with eleven.
const EMAILS = path.resolve(__dirname, "../../../backend/tests/fixtures/emails");
const LINKEDIN = path.join(EMAILS, "linkedin-alert-vice-president-bangalore-2026-10-29.eml");
const NAUKRI = path.join(EMAILS, "naukri-alert-recommended-jobs-2026-09-21.eml");

const DESCRIPTION =
  "Commonwealth Bank is hiring a Chief Engineer in Bengaluru to lead platform engineering, " +
  "own the architecture of core banking services and grow a team of 150 engineers.";

// Needs the stack with ENV=local (the default for `make up` and `make dev`): the Inbox's "Upload .eml"
// stands in for Gmail forwarding, and the worker must be running to read the emails.
test("alert emails become jobs: upload, read, filter, open, paste a description, ignore and restore", async ({ page }) => {
  test.setTimeout(90_000);
  const email = `e2e-jobs-${Date.now()}@example.com`;
  const nav = page.getByRole("navigation", { name: "Main" });

  await page.goto("/sign-up");
  await page.getByLabel("First name", { exact: true }).fill("Jobs");
  await page.getByLabel("Last name", { exact: true }).fill("Tester");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Re-enter password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Where do you want to work?").fill("Bengaluru, Remote");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Jobs" })).toBeVisible();
  await expect(page.getByTestId("jobs-card")).toContainText("0 new");

  // Empty Jobs page points to mail setup.
  await nav.getByRole("link", { name: "Jobs", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No jobs yet" })).toBeVisible();
  await page.getByRole("link", { name: "Set up forwarding" }).click();
  await expect(page.getByRole("heading", { name: "Mail setup" })).toBeVisible();
  await expect(page.getByTestId("mail-address")).toHaveText(/^alerts-[a-z2-9]{10}@/);

  // Forwarding by hand instead of a filter: list the address you forward from (and take it off again).
  const byHand = page.getByTestId("forward-by-hand");
  await byHand.getByLabel("Address you forward from").fill("me-e2e@gmail.com");
  await byHand.getByRole("button", { name: "Add address" }).click();
  await expect(byHand.getByTestId("forward-sender")).toHaveText(/me-e2e@gmail\.com/);
  await byHand.getByRole("button", { name: "Remove me-e2e@gmail.com" }).click();
  await expect(byHand.getByTestId("forward-sender")).toHaveCount(0);

  // Deliver two alert emails; the worker reads them and the Inbox updates itself.
  await nav.getByRole("link", { name: "Inbox", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Nothing received yet" })).toBeVisible();
  await page.getByTestId("eml-input").setInputFiles([LINKEDIN, NAUKRI]);
  await expect(page.getByText("2 emails delivered.")).toBeVisible();
  const rows = page.getByTestId("inbox-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.filter({ hasText: "LinkedIn job alert" })).toContainText("Read", { timeout: 30_000 });
  await expect(rows.filter({ hasText: "Naukri recommendations" })).toContainText("Read", { timeout: 30_000 });
  await expect(rows.filter({ hasText: "LinkedIn job alert" })).toContainText("vice president in Bangalore Urban");

  // Uploading the same email again is refused as a duplicate.
  await page.getByTestId("eml-input").setInputFiles(LINKEDIN);
  await expect(page.getByText("This email has already been received")).toBeVisible();

  // All 17 jobs are listed; filters narrow them down and survive in the URL.
  await nav.getByRole("link", { name: "Jobs", exact: true }).click();
  // No resume in this test, so nothing is scored: the "All" tab lists every job.
  await expect(page.getByText("Add your resume to see match scores")).toBeVisible();
  await page.getByRole("group", { name: "Queue" }).getByRole("button", { name: /^All/ }).click();
  await expect(page.getByTestId("jobs-total")).toHaveText("17 jobs");
  await page.getByLabel("Source").selectOption("linkedin");
  await expect(page.getByTestId("jobs-total")).toHaveText("6 jobs");
  await expect(page).toHaveURL(/tab=all.*source=linkedin/);
  await page.getByLabel("Search jobs").fill("commonwealth");
  await expect(page.getByTestId("jobs-total")).toHaveText("1 job");
  const card = page.getByTestId("job-card");
  await expect(card).toContainText("Chief Engineer");
  await expect(card).toContainText("New");
  await expect(card.getByTestId("job-source")).toHaveText("LinkedIn");
  // Where to apply is one click away, from the list and from the job.
  await expect(card.getByTestId("apply-link")).toHaveAttribute("href", "https://www.linkedin.com/jobs/view/4484420848/");

  // Open it: marked seen, links to the public LinkedIn page, and takes a pasted description.
  await card.getByRole("link", { name: "Chief Engineer" }).click();
  await expect(page.getByRole("heading", { name: "Chief Engineer" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Apply on LinkedIn ↗" })).toHaveAttribute(
    "href",
    "https://www.linkedin.com/jobs/view/4484420848/",
  );
  await expect(page.getByRole("link", { name: "Open on LinkedIn ↗" })).toHaveAttribute(
    "href",
    "https://www.linkedin.com/jobs/view/4484420848/",
  );
  await page.getByRole("button", { name: "Paste description" }).click();
  await page.getByLabel("Full job description").fill(DESCRIPTION);
  await page.getByRole("button", { name: "Save description" }).click();
  await expect(page.getByTestId("job-description")).toHaveText(DESCRIPTION);
  await expect(page.getByText("Pasted by you · visible only to you")).toBeVisible();

  // Back keeps the filters; the job is no longer new.
  await page.goBack();
  await expect(page).toHaveURL(/tab=all.*source=linkedin/);
  await expect(page.getByLabel("Source")).toHaveValue("linkedin");

  await page.goto("/jobs?tab=all&q=commonwealth");
  await expect(page.getByTestId("jobs-total")).toHaveText("1 job");
  await expect(page.getByTestId("job-card")).not.toContainText("New");

  // Ignore moves it to the Ignored tab, which can restore it.
  await page.goto("/jobs?tab=unscored&q=commonwealth");
  const queues = page.getByRole("group", { name: "Queue" });
  await page.getByRole("button", { name: "Ignore Chief Engineer" }).click();
  await expect(page.getByText("No jobs match these filters.")).toBeVisible();
  await queues.getByRole("button", { name: /^Ignored/ }).click();
  await expect(page.getByTestId("job-card")).toContainText("Chief Engineer");
  await page.getByRole("button", { name: "Restore" }).click();
  await expect(page.getByTestId("job-card")).toHaveCount(0);
  await queues.getByRole("button", { name: /^Not scored yet/ }).click();
  await expect(page.getByTestId("job-card")).toContainText("Chief Engineer");

  // Recruiter-invite and outside-preference markers come from the Naukri email.
  await page.goto("/jobs?tab=all&source=naukri");
  await expect(page.getByTestId("jobs-total")).toHaveText("11 jobs");
  await expect(page.getByTestId("job-card").filter({ hasText: "Outside your preference" })).toHaveCount(4);

  // The dashboard counts them: 17 received, 16 still new (one was opened).
  await nav.getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(page.getByTestId("jobs-card")).toContainText("16 new");
  await expect(page.getByTestId("jobs-card")).toContainText(/Active jobs\s*17/);
});
