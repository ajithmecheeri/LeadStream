import path from "node:path";
import { expect, test } from "@playwright/test";

// Milestone 14.1–14.3: fill the apply profile, see it in a job's Apply kit, make a pairing code for the extension.
const EMAILS = path.resolve(__dirname, "../../../backend/tests/fixtures/emails");
const LINKEDIN = path.join(EMAILS, "linkedin-alert-vice-president-bangalore-2026-10-29.eml");

test("apply profile → Apply kit on a job → pair the browser extension", async ({ page, context }) => {
  test.setTimeout(90_000);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/sign-up");
  await page.getByLabel("First name", { exact: true }).fill("Kit");
  await page.getByLabel("Last name", { exact: true }).fill("Tester");
  await page.getByLabel("Email", { exact: true }).fill(`e2e-apply-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Re-enter password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Where do you want to work?").fill("Bengaluru, Remote");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Kit" })).toBeVisible();

  await page.goto("/profile#apply");
  const apply = page.getByTestId("apply-profile");
  await apply.getByLabel("Phone").fill("+91 90000 00001");
  await apply.getByLabel("Postal code").fill("560001");
  await apply.getByRole("button", { name: "Add a role" }).click();
  await apply.getByTestId("work-entry").getByLabel("Job title").fill("VP, Engineering");
  // Typed key by key: a space must survive the next keystroke (feedback 2026-11-10, "Master's Degree").
  await apply.getByTestId("work-entry").getByLabel("Company").pressSequentially("Example Fintech ");
  await expect(apply.getByTestId("work-entry").getByLabel("Company")).toHaveValue("Example Fintech ");
  await apply.getByTestId("work-entry").getByLabel("I currently work here").check();
  await apply.getByRole("button", { name: "Save for application forms" }).click();
  await expect(apply).toContainText("Saved");

  await page.goto("/inbox");
  await page.getByTestId("eml-input").setInputFiles(LINKEDIN);
  await expect(page.getByTestId("inbox-row")).not.toContainText("Reading", { timeout: 30_000 });
  await page.goto("/jobs?tab=unscored");
  await page.getByTestId("job-card").getByRole("link", { name: "Chief Engineer" }).click();
  const kit = page.getByTestId("apply-kit");
  await kit.getByRole("button", { name: "Show fields to copy" }).click();
  await expect(kit.getByTestId("kit-field").filter({ hasText: "Phone" })).toContainText("+91 90000 00001");
  await expect(kit.getByTestId("kit-field").filter({ hasText: "Job title (1)" })).toContainText("VP, Engineering");
  await expect(kit.getByTestId("kit-field").filter({ hasText: "Company" })).toContainText("Example Fintech");
  await expect(kit).toContainText("I currently work here");
  await kit.getByRole("button", { name: "Copy Phone" }).click();
  await expect(kit.getByRole("button", { name: "Copy Phone" })).toHaveText("Copied");

  await page.goto("/settings");
  const ext = page.getByTestId("browser-extension");
  await ext.getByRole("button", { name: "Pair a browser" }).click();
  await expect(ext.getByTestId("pairing-code")).toContainText("bmjpair.");
});
