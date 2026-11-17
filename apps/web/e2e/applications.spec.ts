import path from "node:path";
import { expect, test } from "@playwright/test";

// Milestone 5: mark a job Applied and track it, mark one Expired and restore it, save a contact on a job.
const EMAILS = path.resolve(__dirname, "../../../backend/tests/fixtures/emails");
const LINKEDIN = path.join(EMAILS, "linkedin-alert-vice-president-bangalore-2026-10-29.eml");

const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

test("applied and expired queues, the applications tracker and contacts", async ({ page }) => {
  test.setTimeout(90_000);
  const nav = page.getByRole("navigation", { name: "Main" });

  await page.goto("/sign-up");
  await page.getByLabel("First name", { exact: true }).fill("Track");
  await page.getByLabel("Last name", { exact: true }).fill("Tester");
  await page.getByLabel("Email", { exact: true }).fill(`e2e-apps-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Re-enter password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Where do you want to work?").fill("Bengaluru, Remote");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Track" })).toBeVisible();

  await nav.getByRole("link", { name: "Inbox", exact: true }).click();
  await page.getByTestId("eml-input").setInputFiles(LINKEDIN);
  // "Reading…" also contains "Read": wait for it to finish first.
  await expect(page.getByTestId("inbox-row")).not.toContainText("Reading", { timeout: 30_000 });
  await expect(page.getByTestId("inbox-row")).toContainText("Read");

  // No resume, so the six jobs wait in "Not scored yet". Applied moves one to the Applied tab.
  await page.goto("/jobs?tab=unscored");
  const queues = page.getByRole("group", { name: "Queue" });
  await expect(page.getByTestId("jobs-total")).toHaveText("6 jobs");
  await page.getByRole("button", { name: "Mark Chief Engineer as applied" }).click();
  await expect(page.getByTestId("jobs-total")).toHaveText("5 jobs");
  await queues.getByRole("button", { name: /^Applied/ }).click();
  const applied = page.getByTestId("job-card");
  await expect(applied).toHaveCount(1);
  await expect(applied.getByTestId("application-status")).toHaveText("Applied");

  // Track it: move to Interviewing, add a note, set a follow-up that's due.
  await applied.getByRole("link", { name: "Track" }).click();
  await expect(page.getByRole("heading", { name: "Applications" })).toBeVisible();
  const app = page.getByTestId("application");
  await expect(app).toContainText("Chief Engineer");
  const timeline = app.getByTestId("timeline");
  await expect(timeline).toContainText("Marked as applied");
  await app.getByLabel("Status of Chief Engineer").selectOption("interviewing");
  await expect(timeline).toContainText("Applied → Interviewing");
  await app.getByLabel("Add a note").fill("First round with the CTO on Monday");
  await app.getByRole("button", { name: "Add note" }).click();
  await expect(timeline).toContainText("First round with the CTO on Monday");
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  await app.getByLabel("Follow-up date for Chief Engineer").fill(isoDay(yesterday));
  await expect(app.getByTestId("follow-up-due")).toBeVisible();

  // The dashboard lists the follow-up; the job page shows it as an amber to-do.
  await nav.getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(page.getByTestId("follow-ups")).toContainText("Chief Engineer");
  await expect(page.getByTestId("jobs-card")).toContainText("1 applied");
  await page.goto("/jobs?tab=applied");
  await expect(page.getByTestId("todo-count")).toHaveText("1 to do");
  await page.getByTestId("job-card").getByRole("link", { name: "Chief Engineer" }).click();
  await expect(page.getByTestId("todo-panel").getByTestId("todo")).toContainText("Follow up on this application");

  // The bell (6.2) lists the follow-up as new; opening it marks it read.
  await page.reload();
  await expect(page.getByTestId("bell-count")).toHaveText("1");
  await page.getByTestId("bell").click();
  await expect(page.getByTestId("bell-item")).toContainText("Follow up on your application");
  await page.getByTestId("bell").click();
  await expect(page.getByTestId("bell-count")).toHaveCount(0);

  // Expired moves a job out of the active list; Restore brings it back.
  await page.goto("/jobs?tab=unscored");
  await page.getByRole("button", { name: "Mark SEG & India CFO as expired" }).click();
  await expect(page.getByTestId("jobs-total")).toHaveText("4 jobs");
  await expect(queues.getByRole("button", { name: /^Expired/ })).toContainText("1");
  await page.goto("/jobs?tab=expired");
  await expect(page.getByTestId("jobs-total")).toHaveText("1 job");
  await expect(page.getByTestId("job-card")).toContainText("SEG & India CFO");
  await page.getByRole("button", { name: "Restore" }).click();
  await expect(page.getByTestId("job-card")).toHaveCount(0);

  // Contacts: save the recruiter found on the listing. BrewMyJob only keeps it.
  await page.goto("/jobs?tab=unscored");
  await page.getByTestId("job-card").filter({ hasText: "SEG & India CFO" }).getByRole("link", { name: "SEG & India CFO" }).click();
  const contacts = page.getByTestId("contacts");
  await contacts.getByRole("button", { name: "Add a contact" }).click();
  await contacts.getByLabel("Name").fill("Priya Nair");
  await contacts.getByLabel("Role").fill("Recruiter");
  await contacts.getByLabel("LinkedIn profile").fill("linkedin.com/in/priya-nair-example");
  await contacts.getByRole("button", { name: "Save contact" }).click();
  const saved = contacts.getByTestId("contact");
  await expect(saved).toContainText("Priya Nair");
  await expect(saved.getByRole("link", { name: "LinkedIn profile ↗" })).toHaveAttribute("href", "https://linkedin.com/in/priya-nair-example");

  // Saved contacts are highlighted at the top of the job too.
  await page.reload();
  const who = page.getByTestId("who-to-contact");
  await expect(who).toContainText("Priya Nair");
  await expect(who.getByRole("link", { name: "LinkedIn profile ↗" })).toHaveAttribute("href", "https://linkedin.com/in/priya-nair-example");
});
