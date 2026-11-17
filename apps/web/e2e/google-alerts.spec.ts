import { expect, test } from "@playwright/test";

// Google Alerts by RSS (2026-11-15) and the coffee mug in the brand. The test never reaches Google: it only checks
// the page, the steps and that a link other than an alert feed is refused.
test("find on Google: Google Alerts steps and a refused feed link", async ({ page }) => {
  await page.goto("/sign-up");
  await page.getByLabel("First name", { exact: true }).fill("Ravi");
  await page.getByLabel("Last name", { exact: true }).fill("Menon");
  await page.getByLabel("Email", { exact: true }).fill(`e2e-alerts-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Re-enter password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Where do you want to work?").fill("Bengaluru");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Ravi" })).toBeVisible();
  await expect(page.locator(".brand-mug svg")).toBeVisible();

  // On Find on Google since 2026-11-17 (Job sources is for admins).
  await page.goto("/jobs/find");
  await expect(page.getByRole("heading", { name: "Find jobs on Google" })).toBeVisible();
  const alerts = page.getByTestId("google-alerts");
  await expect(alerts.getByRole("heading", { name: "Google Alerts" })).toBeVisible();
  await expect(alerts.getByText("Deliver to")).toBeVisible();
  await expect(alerts.getByText("Add the roles you want at the top of this page")).toBeVisible();

  // Up to five roles of the user's own, set on top of the page for the searches and the alerts (2026-11-17):
  // each gets an alert per job location.
  const roles = page.getByTestId("google-roles");
  await roles.getByRole("button", { name: "Add roles" }).click();
  await roles.getByLabel("Role 1").fill("(Technology Director OR Engineering Director) (Bengaluru OR Bangalore)");
  await roles.getByLabel("Role 2").fill("VP Engineering");
  await roles.getByRole("button", { name: "Save roles" }).click();
  const suggestions = page.getByTestId("alert-suggestions").locator("li");
  await expect(suggestions).toHaveCount(2);
  // Saved the way Google needs it; it names its city, so it gets one alert as written.
  await expect(page.getByTestId("alert-roles")).toContainText('("Technology Director" OR "Engineering Director") ("Bengaluru" OR "Bangalore")');
  await expect(suggestions.nth(1)).toContainText("VP Engineering");
  await expect(suggestions.nth(1)).toContainText("Bengaluru");
  await expect(suggestions.first().getByRole("link", { name: "Create alert ↗" })).toHaveAttribute("href", /google\.com\/alerts\?q=/);
  await expect(page.getByTestId("alert-roles")).toContainText("Roles (yours)");

  await alerts.getByLabel("RSS feed link").fill("https://www.example.com/alerts/feeds/123/456");
  await alerts.getByRole("button", { name: "Add feed" }).click();
  await expect(alerts.getByText("Paste the alert's RSS feed link")).toBeVisible();
  await expect(page.getByTestId("alert-feed")).toHaveCount(0);
});
