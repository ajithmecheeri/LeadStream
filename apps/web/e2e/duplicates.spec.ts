import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test } from "@playwright/test";

// Milestone 9.3: the same role twice (another city) is flagged "Possible duplicate"; "Same job" merges the two and
// "Not the same job" undoes it. The jobs come from an AI assistant's list sent from the user's own address (9.4b),
// which is read only once that address is listed on Mail setup.
const ME = "dup-tester@example.com";

function assistantEmail(): string {
  const body = [
    "Bengaluru leadership roles",
    "",
    "1) Acme Cloud — VP Engineering",
    "Location: Bengaluru | Hybrid",
    "Posted: 2 days ago",
    "Apply:",
    "https://careers.acme.example/jobs/101",
    "",
    "2) Acme Cloud — VP Engineering",
    "Location: Pune | Hybrid",
    "Posted: 2 days ago",
    "Apply:",
    "https://careers.acme.example/jobs/102",
    "",
  ].join("\r\n");
  const raw = [
    `From: Dup Tester <${ME}>`,
    `To: ${ME}`,
    "Subject: New leadership roles",
    `Date: ${new Date().toUTCString()}`,
    `Message-ID: <e2e-dup-${Date.now()}@example.com>`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=utf-8",
    "",
    body,
  ].join("\r\n");
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "e2e-dup-")), "assistant.eml");
  fs.writeFileSync(file, raw);
  return file;
}

test("a possible duplicate is flagged, merged with Same job, and the merge undone", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/sign-up");
  await page.getByLabel("First name", { exact: true }).fill("Dup");
  await page.getByLabel("Last name", { exact: true }).fill("Tester");
  await page.getByLabel("Email", { exact: true }).fill(`e2e-dup-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Re-enter password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Where do you want to work?").fill("Bengaluru, Remote");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Dup" })).toBeVisible();

  await page.goto("/settings/mail");
  await page.getByLabel("Address you forward from").fill(ME);
  await page.getByRole("button", { name: "Add address" }).click();
  await expect(page.getByTestId("forward-sender")).toContainText(ME);

  await page.goto("/inbox");
  await page.getByTestId("eml-input").setInputFiles(assistantEmail());
  await expect(page.getByTestId("inbox-row")).not.toContainText("Reading", { timeout: 30_000 });
  await expect(page.getByTestId("inbox-row")).toContainText("AI assistant job list");

  await page.goto("/jobs?tab=unscored");
  await expect(page.getByTestId("jobs-total")).toHaveText("2 jobs");
  await expect(page.getByTestId("possible-duplicate-badge")).toHaveCount(2);
  await expect(page.getByTestId("unverified-badge")).toHaveCount(2);

  await page.getByTestId("possible-duplicate-badge").first().click();
  const pair = page.getByTestId("possible-duplicate");
  await expect(pair).toBeVisible();
  await pair.getByRole("button", { name: "Same job" }).click();
  await expect(page.getByTestId("duplicates")).toContainText("Not the same job");

  await page.goto("/jobs?tab=unscored");
  await expect(page.getByTestId("jobs-total")).toHaveText("1 job");
  await expect(page.getByTestId("possible-duplicate-badge")).toHaveCount(0);

  await page.getByTestId("job-card").getByRole("link", { name: "VP Engineering" }).click();
  await page.getByTestId("duplicates").getByRole("button", { name: "Not the same job" }).click();
  await page.goto("/jobs?tab=unscored");
  await expect(page.getByTestId("jobs-total")).toHaveText("2 jobs");
  await expect(page.getByTestId("possible-duplicate-badge")).toHaveCount(0);

  // Milestone 13 A: "Not for me" with a reason ignores the job and is learned, listed on Profile to remove.
  await page.getByTestId("job-card").first().getByRole("link", { name: "VP Engineering" }).click();
  await page.getByRole("button", { name: "Not for me" }).click();
  const form = page.getByTestId("not-for-me-form");
  await form.getByLabel(/Not this company/).check();
  await form.getByRole("button", { name: "Not for me" }).click();
  await expect(page.getByTestId("ignored-notice")).toContainText("Not for you: Not this company");
  await expect(page.getByTestId("learned-notice")).toContainText("Jobs at Acme Cloud");
  await page.goto("/profile#learned");
  const learned = page.getByTestId("learned");
  await expect(learned.getByTestId("learned-item")).toContainText("Jobs at Acme Cloud");
  await learned.getByRole("button", { name: "Remove Jobs at Acme Cloud" }).click();
  await expect(learned.getByTestId("learned-item")).toHaveCount(0);
});
