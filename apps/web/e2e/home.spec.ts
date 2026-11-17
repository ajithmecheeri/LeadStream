import { expect, test } from "@playwright/test";

// Milestone 10: the public home page and its waitlist.
test("the home page explains BrewMyJob and takes a waitlist email", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/BrewMyJob/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("The three jobs worth your evening out.");
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute("content", /opengraph-image/);

  // The FAQ opens one answer at a time.
  const faq = page.locator("#faq details");
  await expect(faq.first()).toHaveAttribute("open", "");
  await faq.nth(1).locator("summary").click();
  await expect(faq.nth(1)).toHaveAttribute("open", "");

  const form = page.locator("#waitlist");
  await form.getByRole("button", { name: "Join the waitlist" }).click();
  await expect(form.getByRole("alert")).toContainText("Enter your email address");
  await form.getByLabel("Email address").fill(`e2e-waitlist-${Date.now()}@example.com`);
  await form.getByRole("button", { name: "Join the waitlist" }).click();
  await expect(page.getByTestId("waitlist-done")).toContainText("You're on the list");

  // Existing users get to the app from here.
  await page.getByRole("navigation", { name: "Footer" }).getByRole("link", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/sign-in/);
});

test("robots and sitemap point search engines at the public pages only", async ({ request }) => {
  const robots = await (await request.get("/robots.txt")).text();
  expect(robots).toContain("Allow: /$");
  expect(robots).toContain("Disallow: /");
  expect(robots).toContain("Allow: /privacy");
  const sitemap = await (await request.get("/sitemap.xml")).text();
  expect(sitemap).toContain("<loc>https://brewmyjob.com</loc>");
  expect(sitemap).toContain("<loc>https://brewmyjob.com/terms</loc>");
});

test("privacy, terms and contact pages; a contact message is received", async ({ page }) => {
  await page.goto("/");
  const footer = page.getByRole("navigation", { name: "Footer" });
  await footer.getByRole("link", { name: "Privacy" }).click();
  await expect(page.getByRole("heading", { name: "Privacy policy", level: 1 })).toBeVisible();
  await expect(page.getByTestId("legal-draft")).toBeVisible();
  await page.getByRole("navigation", { name: "Site" }).getByRole("link", { name: "Terms" }).click();
  await expect(page.getByRole("heading", { name: "Terms of use", level: 1 })).toBeVisible();
  await page.getByRole("navigation", { name: "Site" }).getByRole("link", { name: "Contact" }).click();

  const form = page.getByTestId("contact-form");
  await form.getByRole("button", { name: "Send message" }).click();
  await expect(form).toContainText(/at least|required|valid/i);
  await form.getByLabel("Your name").fill("E2E Visitor");
  await form.getByLabel("Email address").fill(`e2e-contact-${Date.now()}@example.com`);
  await form.getByLabel("About").selectOption("feedback");
  await form.getByLabel("Message").fill("The duplicate detection saved me two applications.");
  await form.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByTestId("contact-done")).toContainText("reached the BrewMyJob team");
});
