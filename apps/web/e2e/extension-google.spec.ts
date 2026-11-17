import path from "node:path";
import { expect, test } from "@playwright/test";

// POC (user, 2026-11-17): the extension's "Add to BrewMyJob" button on Google's results (apps/extension/src/google.js),
// on a hand-made page shaped like Google's. chrome.runtime is stubbed: the API side is in
// backend/tests/test_extension_google.py. Delete this file with the POC.
const SRC = path.resolve(__dirname, "../../extension/src");

const PAGE = `<div id="search">
  <div class="MjjYud"><div class="g">
    <div><a href="/url?q=https://in.linkedin.com/jobs/view/head-of-engineering-at-acme-group-4490581539&sa=U"><h3>Acme Group hiring Head of Engineering in Bengaluru | LinkedIn</h3><cite>in.linkedin.com</cite></a></div>
    <div class="VwiC3b">Lead a team of 40 engineers building payments.</div>
  </div></div>
  <div class="MjjYud"><div class="g">
    <div><a href="https://www.naukri.com/job-listings-director-engineering-example-tech-bengaluru-15-to-20-years-121125000123"><h3>Director Engineering - Example Tech - Naukri.com</h3></a></div>
    <div class="VwiC3b">Example Tech is hiring a Director.</div>
  </div></div>
  <div class="MjjYud"><div class="g">
    <div><a href="https://www.linkedin.com/in/someone"><h3>Someone | LinkedIn</h3></a></div>
  </div></div>
  <div class="MjjYud"><div class="g">
    <div><a href="https://careers.example.com/jobs/1"><h3>Engineer at Example</h3></a></div>
  </div></div>
</div>`;

test("puts Add to BrewMyJob only on portal job results and sends Google's fields on click", async ({ page }) => {
  await page.setContent(PAGE);
  await page.evaluate(() => {
    const w = window as unknown as { sent: unknown[]; chrome: unknown };
    w.sent = [];
    w.chrome = {
      runtime: {
        id: "test",
        sendMessage: async (m: unknown) => {
          w.sent.push(m);
          return { ok: true, value: { already: false, link: "http://localhost:8080/jobs/1" } };
        },
      },
    };
  });
  await page.addScriptTag({ path: path.join(SRC, "google.js") });

  // A LinkedIn job and a Naukri job; not a LinkedIn profile, not a company's own site.
  await expect(page.getByTestId("bmj-add")).toHaveCount(2);
  await page.getByRole("button", { name: "+ Add to BrewMyJob" }).first().click();
  await expect(page.getByText("Added to From Google ✓")).toBeVisible();
  await expect(page.getByRole("link", { name: "Review in BrewMyJob" })).toHaveAttribute("href", "http://localhost:8080/jobs/1");
  const sent = await page.evaluate(() => (window as unknown as { sent: unknown[] }).sent);
  expect(sent).toEqual([
    {
      type: "google-result",
      url: "https://in.linkedin.com/jobs/view/head-of-engineering-at-acme-group-4490581539",
      title: "Acme Group hiring Head of Engineering in Bengaluru | LinkedIn",
      snippet: "Lead a team of 40 engineers building payments.",
    },
  ]);

  // Results Google adds later (scrolling) get the button too.
  await page.evaluate(() => {
    const d = document.createElement("div");
    d.innerHTML = `<div class="g"><div><a href="https://www.foundit.in/job/vp-engineering-example-co-123"><h3>VP Engineering - Example Co</h3></a></div></div>`;
    document.getElementById("search")!.append(d);
  });
  await expect(page.getByTestId("bmj-add")).toHaveCount(3);
});
