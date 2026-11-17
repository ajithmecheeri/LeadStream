import { expect, test } from "@playwright/test";

const RESUME = `E2E TESTER
VP, ENGINEERING | CLOUD PLATFORMS
e2e@example.com • Bengaluru, India
SUMMARY
Engineering leader with 18 years building cloud platforms for banks.
EXPERIENCE
VP, Engineering | Example Bank	Jan 2020 – Present
Led platform teams on AWS.
SKILLS
AWS, Kubernetes, Python, Leadership, Microservices`;

test("sign up, fill the profile, add a resume and tune its Skill Match profile, sign out and back in", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;
  const password = "e2e-password-123";

  await page.goto("/sign-up");
  await page.getByLabel("First name", { exact: true }).fill("E2E");
  await page.getByLabel("Middle name", { exact: true }).fill("Q");
  await page.getByLabel("Last name", { exact: true }).fill("Tester");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("checkbox").check();

  // The password is typed twice; a mismatch is caught before anything is sent.
  await page.getByLabel("Re-enter password", { exact: true }).fill(password + "x");
  await page.getByLabel("Where do you want to work?").fill("Bengaluru, Remote");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("The passwords don't match")).toBeVisible();
  await page.getByLabel("Re-enter password", { exact: true }).fill(password);
  await page.getByLabel("Where do you want to work?").fill("Bengaluru, Remote");
  await expect(page.getByText("Passwords match.")).toBeVisible();

  // Show reveals what was typed; Hide masks it again.
  const field = page.getByLabel("Password", { exact: true });
  await expect(field).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Show password" }).first().click();
  await expect(field).toHaveAttribute("type", "text");
  await page.getByRole("button", { name: "Hide password" }).click();
  await expect(field).toHaveAttribute("type", "password");

  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, E2E" })).toBeVisible();
  await expect(page.getByText("E2E Q Tester")).toBeVisible(); // the full name, from the three parts
  await expect(page.getByTestId("forwarding-address")).toHaveText(/^alerts-[a-z2-9]{10}@/);

  await page.getByRole("link", { name: "Profile", exact: true }).click();
  await page.getByLabel("Years of experience", { exact: true }).fill("18");
  await page.getByRole("button", { name: "Save profile" }).click();
  await expect(page.getByText("Profile saved.")).toBeVisible();

  // A resume brings its own Skill Match profile, made from it (user feedback 2026-11-13).
  await page.getByTestId("resume-library").getByRole("button", { name: "Paste text" }).click();
  await page.getByLabel("resume name").fill("Cloud");
  await page.getByLabel("resume text").fill(RESUME);
  await page.getByTestId("resume-library").getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByTestId("resume-item")).toHaveCount(1);

  // The old Search profiles address lands on the Skill Match Profile tab.
  await page.goto("/search-profiles/new");
  await expect(page).toHaveURL(/\/profile\?tab=match/);
  const profile = page.getByTestId("match-profile");
  await expect(profile).toContainText("From the resume “Cloud”");
  await expect(profile.getByTestId("resume-skills")).toContainText("Kubernetes");

  await profile.getByRole("button", { name: "Edit Cloud" }).click();
  await page.getByLabel("Locations", { exact: true }).fill("Bengaluru,");
  const added = page.getByRole("textbox", { name: /^Skills you added/ });
  await added.fill("Kafka, FinOps");
  await added.press("Enter");
  await expect(page.getByText("Skills you added (2 of 40)")).toBeVisible();
  await page.getByRole("button", { name: "Make skills count more (15 of 100)" }).click();
  await expect(page.getByRole("slider", { name: "Skills" })).toHaveValue("15");
  await page.getByLabel("AI/GenAI", { exact: true }).fill("30");
  await expect(page.getByText("100 / 100")).toBeVisible();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(profile.getByTestId("added-skills")).toContainText("FinOps");
  // Skills added here but missing from the resume are flagged, so the resume can catch up.
  await expect(profile.getByTestId("out-of-sync")).toContainText("Kafka, FinOps");

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/sign-in/);
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, E2E" })).toBeVisible();

  // The session survives a reload (refresh cookie).
  await page.reload();
  await expect(page.getByRole("heading", { name: "Welcome, E2E" })).toBeVisible();
});
