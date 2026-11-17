import path from "node:path";
import { expect, test } from "@playwright/test";

// Milestone 7: import LinkedIn connections, see the warm path on a Top match, act on today's list, track it.
const FIXTURES = path.resolve(__dirname, "../../../backend/tests/fixtures");
const LINKEDIN = path.join(FIXTURES, "emails/linkedin-alert-vice-president-bangalore-2026-10-29.eml");
const CONNECTIONS = path.join(FIXTURES, "connections/Connections.csv"); // fictional people

const RESUME = `ASHA RAO
VP, ENGINEERING | CLOUD AND AI PLATFORMS | Bengaluru, India
Engineering leader with 21+ years building cloud-native banking platforms. Led GenAI and LLM features,
AWS and Azure migrations, and teams of 80 engineers. Chief engineer for core banking services.
VP, Engineering | Example Bank Tech - Bengaluru\tJan 2021 - Present
Director, Engineering | Sample Retail Tech - Bengaluru\tMar 2015 - Dec 2020
Skills: AWS, Azure, Kubernetes, Microservices, LLMs, Architecture, Banking`;

test("connections become warm paths and today's suggestions, tracked as outreach", async ({ page }) => {
  test.setTimeout(150_000);
  const nav = page.getByRole("navigation", { name: "Main" });

  await page.goto("/sign-up");
  await page.getByLabel("First name", { exact: true }).fill("Asha");
  await page.getByLabel("Last name", { exact: true }).fill("Rao");
  await page.getByLabel("Email", { exact: true }).fill(`e2e-net-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Re-enter password", { exact: true }).fill("e2e-password-123");
  await page.getByLabel("Where do you want to work?").fill("Bengaluru, Remote");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Asha" })).toBeVisible();

  await nav.getByRole("link", { name: "Inbox", exact: true }).click();
  await page.getByTestId("eml-input").setInputFiles(LINKEDIN);
  await expect(page.getByTestId("inbox-row")).not.toContainText("Reading", { timeout: 30_000 });
  await nav.getByRole("link", { name: "Profile", exact: true }).click();
  await page.getByTestId("resume-input").setInputFiles({ name: "Asha_Rao_Resume.txt", mimeType: "text/plain", buffer: Buffer.from(RESUME) });
  await expect(page.getByText("1 resume added.")).toBeVisible();
  await page.goto("/jobs");
  await expect(page.getByTestId("job-card").filter({ hasText: "Chief Engineer" }).getByTestId("match-score")).toBeVisible({ timeout: 90_000 });

  // With no connections yet, Networking opens on the import tab.
  await nav.getByRole("link", { name: "Networking", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Import from LinkedIn" })).toBeVisible();
  await page.getByTestId("connections-input").setInputFiles(CONNECTIONS);
  await expect(page.getByText("7 connections read: 7 new, 0 updated.")).toBeVisible();
  await expect(page.getByTestId("connections-count")).toHaveText("7");
  await page.getByLabel("Search connections").fill("talent");
  await expect(page.getByTestId("connections-total")).toHaveText("1 connection");

  // Warm path: two people at Commonwealth Bank, the recruiter first.
  const tabs = page.getByRole("group", { name: "Networking" });
  await tabs.getByRole("button", { name: "Warm paths" }).click();
  const path_ = page.getByTestId("warm-path").filter({ hasText: "Chief Engineer" });
  await expect(path_).toContainText("Meera Shankar (sample)");
  await expect(path_).toContainText("Arjun Pillai (sample)");

  // Today: Meera is suggested with a note; mark it sent and it moves to Outreach.
  await tabs.getByRole("button", { name: "Today" }).click();
  const meera = page.getByTestId("suggestion").filter({ hasText: "Meera Shankar (sample)" });
  await expect(meera.getByTestId("note")).toContainText("Hi Meera,");
  await expect(meera.getByRole("link", { name: "Open profile on LinkedIn ↗" })).toHaveAttribute("href", "https://www.linkedin.com/in/meera-shankar-sample");
  await meera.getByRole("button", { name: "I sent it" }).click();
  await expect(meera).toContainText("Sent");

  await tabs.getByRole("button", { name: "Outreach" }).click();
  const row = page.getByTestId("outreach").filter({ hasText: "Meera Shankar (sample)" });
  await expect(row).toContainText("Chief Engineer");
  await row.getByLabel("Stage for Meera Shankar (sample)").selectOption("accepted");
  await expect(page.getByRole("button", { name: "Accepted (1)" })).toBeVisible();

  // The job page shows who you know there.
  await page.goto("/jobs");
  await page.getByTestId("job-card").filter({ hasText: "Chief Engineer" }).getByRole("link", { name: "Chief Engineer" }).click();
  await expect(page.getByTestId("people-you-know")).toContainText("Meera Shankar (sample)");

  // Applied (feedback 2026-11-15): the company appears on Today with LinkedIn searches for its HR and leaders.
  await page.goto("/jobs");
  await page.getByRole("button", { name: "Mark Chief Engineer as applied" }).click();
  await nav.getByRole("link", { name: "Networking", exact: true }).click();
  await tabs.getByRole("button", { name: "Today" }).click();
  const cba = page.getByTestId("applied-company").filter({ hasText: "Commonwealth Bank" });
  await expect(cba).toContainText("Chief Engineer");
  await expect(cba.getByTestId("search-hr")).toHaveAttribute("href", /^https:\/\/www\.linkedin\.com\/search\/results\/people\/\?keywords=.*Commonwealth%20Bank/);
  await expect(cba.getByTestId("search-leaders")).toBeVisible();
  await expect(cba).toContainText("You know 2 people here");
  await cba.getByRole("button", { name: "I wrote to someone" }).click();
  await cba.getByLabel("Their name").fill("Kavya Iyer");
  await cba.getByLabel("Their role").fill("Talent Acquisition");
  await cba.getByRole("button", { name: "Save as sent" }).click();
  await expect(cba).toContainText("1 contacted");
});
