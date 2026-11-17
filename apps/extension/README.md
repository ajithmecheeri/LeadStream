# BrewMyJob browser extension (milestone 14)

Fills **company application forms** (Workday, Greenhouse, Lever, Ashby, SmartRecruiters and most other forms) from
your BrewMyJob profile, **when you click**. It never clicks Next or Submit, never signs in or signs up, never fills
sensitive questions (race, disability, veteran status, date of birth, ID numbers…; gender and ethnicity only from
the answer you saved for them in the answer bank), and refuses to run on
job portals such as LinkedIn, Naukri or Indeed (CLAUDE.md, non-negotiables). Plain JavaScript, Manifest V3, no build.

## Install (Chrome or Edge, for your own use)

0. Get it: **BrewMyJob → Settings → Browser extension → Download the extension**, and unzip it into a folder you
   keep (or use this folder from the repo).
1. Chrome: `chrome://extensions` (Edge: `edge://extensions`), turn on **Developer mode**.
2. **Load unpacked** and choose the unzipped `brewmyjob-extension` folder (or `apps/extension`). In WSL, use the `\\wsl$\Ubuntu\home\…\apps\extension` path.
3. In BrewMyJob: **Settings → Browser extension → Pair a browser**, copy the code.
4. **In Chrome** (not in the BrewMyJob app): click the puzzle-piece icon (Extensions) at the top right of the toolbar
   and pin **BrewMyJob**. Click its **B** icon: a small window opens. Leave the address as `http://localhost:8080`
   (for `make up`), paste the code into **Pairing code** and click **Pair**. The window then shows **Fill this page**.
   The code lasts 10 minutes and works once.

## Use

Open a company's application form, fill in what needs you (sign in to Workday yourself), then click the BrewMyJob icon →
**Fill this page**. Filled fields turn green; amber ones need you. On Workday, fill one page, check it, click Next
yourself, and click Fill again on the next page.

What it fills comes from **Profile → For application forms** (phone, address, work history, education, languages), your
profile and your **Answer bank**. The suggested resume for the job (or your primary resume) is attached when it was uploaded
as a file.

## Add jobs from Google results (POC, 2026-11-17)

Search on Google (google.com or google.co.in) for LinkedIn, Naukri or Foundit jobs, for example with the searches on
BrewMyJob's **Jobs → Find on Google**. Each job result gets a **+ Add to BrewMyJob** button: click it to add the job
to your Jobs list with what Google shows (title, link, snippet). The job page itself is never opened. Reload the
extension after updating it. How to remove the POC: `docs/plan-m14.md`.

## Files

| File | What |
|---|---|
| `manifest.json` | Permissions: `activeTab` + `scripting` (it sees a page only when you click), `storage` (its token) |
| `src/match.js` | Rules: label → field, sensitive questions, portal block list, option matching. Tested in `apps/web/lib/extension-match.test.ts` |
| `src/fill.js` | Fills the page in view (generic labels; Workday by `data-automation-id`). Tested in `apps/web/e2e/extension-fill.spec.ts` |
| `src/google.js` | POC: the Add to BrewMyJob button on Google results. Tested in `apps/web/e2e/extension-google.spec.ts` |
| `src/background.js` | Talks to the API (`/api/v1/extension/*`) and injects the filler |
| `popup.html`, `popup.js` | Pair, Fill this page, Unpair |

The block list is in `src/match.js` and `backend/app/modules/extension/service.py`; keep them the same.

## Not yet

- Tested on hand-made Greenhouse- and Workday-shaped pages only. Real Workday pages saved by the user ("Save page as",
  sanitised) should become fixtures; Workday's field ids change from time to time.
- Publishing on the Chrome Web Store (needs the deployed API, the privacy policy page and a developer account), icons.
- Questions it doesn't know are left amber; Claude suggestions for them wait for the Anthropic key (14.6).
