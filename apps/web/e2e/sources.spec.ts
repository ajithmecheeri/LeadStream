import { expect, test, type Page } from "@playwright/test";

// Job sources is for admins since 2026-11-17 (docs/plan-roles-and-plans.md), and its companies are one shared
// list: this test only reads it (following and unfollowing are covered by backend/tests/test_sources.py), so it
// never changes the companies of a stack in use. The admin is seeded on a local stack (backend/app/seed.py).
const ADMIN = { email: "e2e-admin@example.com", password: "e2e-admin-password-2026" };

async function signUp(page: Page, first: string, email: string) {
  await page.goto("/sign-up");
  await page.getByLabel("First name", { exact: true }).fill(first);
  await page.getByLabel("Last name", { exact: true }).fill("Iyer");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Re-enter password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Where do you want to work?").fill("Bengaluru, Remote");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();
}

test("job sources: an admin sees the shared companies and their jobs", async ({ page }) => {
  const nav = page.getByRole("navigation", { name: "Main" });
  await page.goto("/sign-in");
  await page.getByLabel("Email", { exact: true }).fill(ADMIN.email);
  await page.getByLabel("Password", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(nav).toBeVisible();

  await nav.getByRole("link", { name: "Job sources" }).click();
  await expect(page.getByRole("heading", { name: "Job sources" })).toBeVisible();
  await expect(page.getByTestId("adzuna")).toContainText(/Not connected yet|search profile|Searches/);
  await expect(page.getByTestId("last-check")).toContainText("Companies are read every 3 hours (next at ");
  // Suggestions come from the service (hidden once every one is on the list).
  await expect(page.getByTestId("company").or(page.getByTestId("suggestions")).first()).toBeVisible();

  // A company on the list: its open jobs, the last check's first (user, 2026-11-16).
  const company = page.getByTestId("company").first();
  if (await company.count()) {
    await company.getByTestId("company-jobs-toggle").click();
    await expect(company.getByTestId("company-jobs")).toBeVisible();
    await company.getByRole("button", { name: "Hide jobs" }).click();
    await expect(company.getByTestId("company-jobs")).toHaveCount(0);
  }
  // Admins don't get the super admin's page.
  await expect(nav.getByRole("link", { name: "Admin settings" })).toHaveCount(0);
});

test("a job seeker: no Job sources, every source's jobs in From sources, Google Alerts on Find on Google", async ({ page }) => {
  const nav = page.getByRole("navigation", { name: "Main" });
  await signUp(page, "Ravi", `e2e-src-${Date.now()}@example.com`);
  await expect(page.getByRole("heading", { name: "Welcome, Ravi" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Job sources" })).toHaveCount(0);

  await nav.getByRole("link", { name: "Jobs", exact: true }).click();
  await page.getByRole("group", { name: "Queue" }).getByRole("button", { name: "From sources" }).click();
  await expect(page).toHaveURL(/tab=sources/);
  await expect(page.getByTestId("from-sources")).toContainText("Jobs from the job sources");
  await expect(page.getByTestId("from-sources").getByTestId("run-jobs")).toBeVisible();

  // Find on Google is a menu item of its own, with Google Alerts (user, 2026-11-17).
  await nav.getByRole("link", { name: "Find on Google" }).click();
  await expect(page.getByRole("heading", { name: "Find jobs on Google" })).toBeVisible();
  await expect(page.getByTestId("google-alerts")).toBeVisible();
});

test("without a plan or an invite, a new account sees the plans", async ({ page }) => {
  // Not an e2e-…@example.com address: this account has no free access.
  await signUp(page, "Meera", `paywall-${Date.now()}@example.org`);
  await expect(page).toHaveURL(/\/plans/);
  await expect(page.getByRole("heading", { name: "Choose a plan" })).toBeVisible();
  const plans = page.getByTestId("plan");
  await expect(plans).toHaveCount(4);
  await expect(plans.nth(0)).toContainText("₹199");
  await expect(plans.nth(1)).toContainText("₹500");
  await expect(plans.nth(2)).toContainText("₹750");
  await expect(plans.nth(3)).toContainText("₹1,200");
  await expect(page.getByText("Online payment opens soon")).toBeVisible();
  // The app stays closed.
  await page.goto("/jobs");
  await expect(page).toHaveURL(/\/plans/);
});
