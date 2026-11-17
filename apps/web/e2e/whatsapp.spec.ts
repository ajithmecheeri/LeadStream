import { expect, test } from "@playwright/test";

// Milestone 6: add a WhatsApp number on Settings; a code is sent (logged without WhatsApp keys) and asked for.
// The code itself is only in the server log, so verification is covered by the backend tests.
test("settings: add a WhatsApp number for job alerts", async ({ page }) => {
  await page.goto("/sign-up");
  await page.getByLabel("First name", { exact: true }).fill("Meera");
  await page.getByLabel("Last name", { exact: true }).fill("Das");
  await page.getByLabel("Email", { exact: true }).fill(`e2e-wa-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Re-enter password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Where do you want to work?").fill("Bengaluru, Remote");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Meera" })).toBeVisible();

  await page.goto("/settings");
  const wa = page.getByTestId("whatsapp");
  await expect(wa).toContainText("A message for each new strong match");
  // With real WhatsApp keys in .env, "Send code" would message the made-up number below for real: skip.
  const live = !(await wa.getByText("WhatsApp sending isn't set up on this server yet").isVisible());
  test.skip(live, "WhatsApp is configured on this stack: the test would send a real message");
  await wa.getByLabel("WhatsApp number").fill("98765 43210");
  await wa.getByRole("button", { name: "Send code" }).click();
  await expect(wa).toContainText("Code sent");
  await expect(wa).toContainText("+91 ••••• 43210");
  await expect(wa).toContainText("Not verified");

  await wa.getByLabel("Code from WhatsApp").fill("000000");
  await wa.getByRole("button", { name: "Verify" }).click();
  await expect(wa).toContainText("That code is not right");

  await wa.getByRole("button", { name: "Remove" }).click();
  await expect(wa.getByLabel("WhatsApp number")).toBeVisible();
});
