# Milestone 6 — Notifications (web first)

Scope and the user's decisions of 2026-11-03 are in `docs/milestones.md` (Milestone 6). This file records what is
built, the decisions made while building, and the one-time WhatsApp setup.

## Status

| Part | What | Status |
|------|------|--------|
| 6.1 | WhatsApp alerts for strong matches: number verified by a code, one message per job, quiet hours, daily limit, test message, recent messages on Settings | built 2026-11-05; sends for real once the Meta setup below is done (until then messages go to the worker log) |
| 6.2 | In-app bell: new top matches (7 days), possible duplicates, follow-ups due, jobs that may have expired; unread count, newest first, refreshed every minute | built 2026-11-09: worked out on read (`notifications/bell.py`, no new table; `notification_settings.bell_seen_at` for unread, migration 0017), `GET /notifications/bell`, `POST /notifications/bell/seen`, bell in the menu bar (`components/Bell.tsx`). Not yet: per-item dismiss (items leave the bell when dealt with) |
| 6.3 | Email digest | waits for outbound email on the domain |
| 6.4 | Reply buttons in WhatsApp (Applied / Ignore) | needs a public webhook (`inbound.brewmyjob.com`) |
| 6b | Expo app and push | later, once the web app is stable |

## What was built (6.1)

- **Backend** `app/modules/notifications/`:
  - `whatsapp.py`: Meta Cloud API client (templates only), number normalising (a 10-digit Indian mobile gets +91);
  - `service.py`: which jobs alert, quiet hours, the daily limit;
  - `tasks.py`: the `notifications.send` worker task, with retries;
  - `router.py`: the endpoints below.
- **Hook:** `matching.service.score_user` calls `alert_new_matches` after every scoring run.
- **Migration 0014:**
  - `notification_settings` gains the WhatsApp number, verification (sha256 of the code only, 10 minutes, 5 tries, one code a minute) and an on/off switch;
  - new private table `notifications` (the outbox, RLS FORCE, `own_rows`), with a unique index for one message per job and channel.
- **API:**
  - `GET /notifications/whatsapp`
  - `POST /notifications/whatsapp/number`
  - `POST /notifications/whatsapp/verify`
  - `PATCH /notifications/whatsapp` (`{jobs}`)
  - `POST /notifications/whatsapp/test`
  - `DELETE /notifications/whatsapp`
- **Web:** a "WhatsApp alerts" card on Settings with these parts:
  - add a number, enter the code, change or remove the number;
  - turn alerts on or off and send a test;
  - recent messages with their status.

  "Max push per day" is now "Max job alerts per day".
- **Tests:**
  - `test_notifications.py`;
  - an isolation test for `notifications`;
  - e2e `whatsapp.spec.ts`.

## Decisions (for the user's review)

1. **Which jobs (user, 2026-11-05: "WhatsApp alert for high match jobs").** This replaces "every new job" from
   2026-11-03. A message is sent when all of these hold:
   - the job is a **Strong match**, at or above the threshold of the search profile it matched (85 by default; the
     search profile editor already said strong matches "notify you right away");
   - it is **new**: first seen in the last 24 hours, and not applied, ignored or expired. So a re-score after a
     weight change never alerts old jobs.
   - it was **never alerted before**: one message per job, ever. A job repeated in a later alert email, or found
     again by a source, doesn't send again.
   Good matches (70 to the threshold) stay in Top matches without a message.
2. **Quiet hours** (Settings, on the user's clock, default 22:00 to 07:00). Messages are held and sent when quiet
   hours end. A held message is dropped if the user applies to or ignores the job meanwhile, or turns alerts off.
3. **Daily limit:** the existing "max per day" setting (default 10), now labelled "Max job alerts per day". The best
   scores go first. Jobs over the limit are not sent later; they are listed as "Not sent: daily limit" and stay in
   Top matches.
4. **The message:** title, company, match %, and a link to the job in BrewMyJob. Only these leave BrewMyJob (to
   Meta); nothing from the resume does. The link uses `PUBLIC_BASE_URL`, so on a phone it opens only once the app
   is on the domain.
5. **Verification:** a 6-digit code sent by WhatsApp (Meta's authentication template). It lasts 10 minutes, allows
   5 tries and one new code a minute. Only its sha256 is stored.
6. **Without keys** (now): codes and alerts are written to the worker log (`make logs`) and shown as "Not sent
   (WhatsApp not set up)". So the flow can be tried, and a number can be "verified" with the code from the log.
7. **Retries:** a network or Meta server error is retried twice (after 2 and 4 minutes). A refusal (number not
   allowed, template missing, bad token) fails at once, and Settings shows Meta's reason.

8. **Number at sign-up (user, 2026-11-05).** Sign-up has an optional WhatsApp number field. It is saved
   unverified and no message is sent at sign-up. Settings then offers **Send code**
   (`POST /notifications/whatsapp/code`), and alerts start once the code is entered. The field is optional
   because many users won't want WhatsApp alerts, and BrewMyJob shouldn't hold a phone number it doesn't need.
   Typing the number is the user's opt-in, which Meta requires before a business may message someone.

## Left to do (WhatsApp setup)

Progress on 2026-11-05: the Brewmyjob business portfolio, the app and the test number exist; the user's number is
on the test number's recipient list and Meta's sample message arrived.

| # | Task | Status |
|---|------|--------|
| 1 | **`job_alert` template.** Meta's check flagged the first wording ("New top match…") as Marketing. Resubmit as Utility with the reworded body (step 4 below). If Meta still insists on Marketing, accept it for testing, then before launch request a Utility review in Business Support Home (Marketing costs more per message, is capped per person, and is easier to block) | **approved** (Active, Marketing, English `en`) on 2026-11-06; the Utility review before launch is still to do. 2026-11-07: the first real alert (Lam Research, 92%) was accepted by Meta (HTTP 200, same template and number as the test that arrived) but never reached the phone. Meta's test-webhook panel confirmed it: status `failed`, error **131049** ("not delivered to maintain healthy ecosystem engagement"), Meta's per-person limit on Marketing messages. So the Utility review is needed now for alerts to arrive reliably, not just before launch; retrying a 131049 doesn't help. Meta reports why a message wasn't delivered only through the status webhook (part 6.4) |
| 2 | **Permanent token.** Business settings, then System users: add `brewmyjob-sender` (Admin), assign the app and the WhatsApp account (full control), generate a token that never expires with `whatsapp_business_messaging` and `whatsapp_business_management`, and put it in `.env` as `WHATSAPP_ACCESS_TOKEN` (replacing any 24-hour token). Then `make up` | pending |
| 3 | `.env`: `WHATSAPP_PHONE_NUMBER_ID` (from Step 1. Try it out), and `WHATSAPP_TEMPLATE_LANGUAGE=en_US` only if the template's language is English (US) | done 2026-11-06 (language left at the default `en`) |
| 4 | Try it: Settings, WhatsApp alerts, **Send a test** | done 2026-11-07: the test job alert arrived on the user's phone. The first try (2026-11-06) was accepted by Meta but not delivered; it worked after a new access token was generated on Step 1. Try it out. Alerts logged before the keys were set no longer count toward the daily limit |
| 5 | Before launch: BrewMyJob's own number, business verification (needs registration documents), display name "BrewMyJob", the `verify_code` template, a payment method | launch |

## One-time WhatsApp setup (free test number)

Meta's test number costs nothing and can message up to 5 numbers you list. Paid sending is decided before launch
(see `docs/milestones.md`).

1. **Create the app.**
   - Go to developers.facebook.com, then **My Apps**, then **Create app**.
   - Choose **Business** as the type, then add the **WhatsApp** product.
   - Meta creates a test WhatsApp Business account with a test phone number.
2. **List your number.** Under **WhatsApp**, then **API Setup**, then **To**, add your own mobile number and enter
   the code Meta sends it. You can list up to 5 numbers.
3. **Get a permanent token.** The token on API Setup expires in 24 hours. For a lasting one:
   - go to **Business settings**, then **System users**, and add a system user (Admin);
   - assign it the app and the WhatsApp account;
   - generate a token with `whatsapp_business_messaging` and `whatsapp_business_management`.
4. **Create two templates** in **WhatsApp Manager**, then **Message templates**, with language English (`en`):
   - **`job_alert`**, category **Utility**. Body:
     `Your BrewMyJob job alert: {{1}} at {{2}} matches your search profile ({{3}}% match). View it: {{4}}. You get this because you turned on WhatsApp alerts in your BrewMyJob settings.`
     Choose **Number** variables, not named ones. Give samples when Meta asks, for example: VP Engineering, Acme, 90,
     https://brewmyjob.com/jobs/1. (The first wording, "New top match: …", was flagged as Marketing on 2026-11-05.)
   - **`verify_code`**, category **Authentication**, with a **Copy code** button. Meta writes the text itself.
5. **Add the keys** to `.env` (never commit them):
   ```
   WHATSAPP_PHONE_NUMBER_ID=<the Phone number ID from API Setup>
   WHATSAPP_ACCESS_TOKEN=<the system user token>
   ```
   Then run `make up`.
6. **Try it.** On Settings, open **WhatsApp alerts**, add your number, enter the code, then press **Send a test**.
