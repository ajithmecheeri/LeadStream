import { expect, test } from "@playwright/test";

// Route 1 (2026-11-14): Google searches the user runs in their own browser, and adding a job they found. The
// test never opens Google or LinkedIn; it only checks the links and the form.
test("find on Google: add a LinkedIn job by its link", async ({ page }) => {
  await page.goto("/sign-up");
  await page.getByLabel("First name", { exact: true }).fill("Meera");
  await page.getByLabel("Last name", { exact: true }).fill("Nair");
  await page.getByLabel("Email", { exact: true }).fill(`e2e-find-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Re-enter password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Where do you want to work?").fill("Bengaluru");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Meera" })).toBeVisible();

  await page.goto("/jobs");
  await page.getByRole("main").getByRole("link", { name: "Find on Google" }).click();
  await expect(page.getByRole("heading", { name: "Find jobs on Google" })).toBeVisible();
  // No resume yet, so no roles to search for; the roles card is on top (user, 2026-11-17).
  await expect(page.getByTestId("google-roles")).toBeVisible();
  await expect(page.getByText("Add roles above (or target roles to your Skill Match Profile)")).toBeVisible();

  // A link from somewhere else is refused with a reason.
  await page.getByLabel("Link to the job").fill("https://careers.example.com/jobs/123");
  await page.getByLabel("Job title").fill("Head of Engineering");
  await page.getByLabel("Company").fill("Example");
  await page.getByRole("button", { name: "Add job" }).click();
  await expect(page.getByText("Only LinkedIn, Naukri and Foundit job links can be added here").first()).toBeVisible();

  // A LinkedIn link fills the title and company it spells out.
  const id = String(Date.now()).slice(-10);
  await page.getByLabel("Job title").fill("");
  await page.getByLabel("Company").fill("");
  await page.getByLabel("Link to the job").fill(`https://in.linkedin.com/jobs/view/head-of-platform-engineering-at-e2e-retail-group-${id}`);
  await expect(page.getByLabel("Job title")).toHaveValue("Head of Platform Engineering");
  await expect(page.getByLabel("Company")).toHaveValue("E2e Retail Group");
  await page.getByLabel("Location (optional)").fill("Bengaluru (Hybrid)");
  await page.getByRole("button", { name: "Add job" }).click();

  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: "Head of Platform Engineering" })).toBeVisible();
});
