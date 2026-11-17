# Cloudflare Email Worker (milestone 2)

Real alert forwarding for **brewmyjob.com**:

```
Gmail filter (LinkedIn / Naukri alerts only)
  → alerts-<token>@in.brewmyjob.com
  → Cloudflare Email Routing → this worker
      reads Cloudflare's DKIM verdict, signs the request (HMAC-SHA256, INBOUND_HMAC_SECRET)
  → https://inbound.brewmyjob.com/internal/inbound  (Cloudflare Tunnel → the api container)
  → the API checks the sender (LinkedIn, Naukri, Gmail's forwarding confirmation) and parses the jobs
```

- **Addresses:** only `alerts-<token>@<INBOUND_DOMAIN>` is accepted; any other address, or mail over 5 MB, is
  bounced. An address the API doesn't know is bounced too, so a mistyped forwarding address fails Gmail's
  confirmation. A sender the API doesn't allow is dropped quietly (no bounce to a stranger).
- **PC off or tunnel down:** the email waits in the `OUTBOX` KV store, and a cron retries every 10 minutes for up
  to 7 days. The API ignores a second delivery of the same Message-ID.
- **DKIM:** the worker trusts only the topmost `(ARC-)Authentication-Results` header, and only when its
  authserv-id is Cloudflare's (`mx.cloudflare.net`). Anything further down came with the message.
- **Logs** (`make email-worker-logs`) show one line per email: the recipient's first 4 token characters, the
  From header, the DKIM results and the outcome. No email content is logged.
- Everything here runs on Cloudflare's free plan.

Tests: `pnpm --filter @fitfirst/email-worker test` (also part of `make test-web`).

## One-time setup

Run the commands in WSL from the repo root. Steps marked **dashboard** are at https://dash.cloudflare.com.

1. **Sign wrangler in to Cloudflare:** `pnpm --filter @fitfirst/email-worker exec wrangler login` opens a
   browser page; allow it.
2. **Outbox store:** `pnpm --filter @fitfirst/email-worker exec wrangler kv namespace create OUTBOX`, then
   paste the `id` it prints into `wrangler.toml` in place of `REPLACE_WITH_OUTBOX_ID`.
3. **Tunnel (dashboard):**
   - Zero Trust → Networks → Tunnels → **Create a tunnel** → Cloudflared → name it `brewmyjob-pc`.
   - On the install page, copy the token (the long string after `--token`) into `.env` as
     `CLOUDFLARE_TUNNEL_TOKEN=…`. Skip the install commands: `make tunnel` runs cloudflared in Docker.
   - **Public hostname:** subdomain `inbound`, domain `brewmyjob.com`, path `^/internal/inbound$`, service
     type `HTTP`, URL `api:8000`. Leave no other hostnames, so nothing else on this PC is reachable.
4. **App settings:** in `.env` set `INBOUND_DOMAIN=in.brewmyjob.com`. Then `make up` (the tunnel reaches the
   `api` container, so use `make up`, not `make dev`), then `make tunnel`.
5. **Shared secret:** `make email-worker-secret`. It writes a new random secret to `.env` and to the worker
   without printing it, and restarts the API.
6. **Deploy:** `make email-worker-deploy`. On a new Cloudflare account the cron needs the account's workers.dev
   subdomain to exist: open **Workers & Pages** in the dashboard once (that creates it), then deploy again. The
   worker itself gets no workers.dev address (`workers_dev = false`).
7. **Email Routing (dashboard):** brewmyjob.com → Email → Email Routing.
   - Turn it on. If asked, let it add its MX and TXT records.
   - Settings → **Subdomains** → add `in`.
   - Routing rules → **Catch-all** for `in.brewmyjob.com` → action **Send to a Worker** → `brewmyjob-email`.
   - If your dashboard offers no catch-all for the subdomain: use the root domain instead. Set
     `INBOUND_DOMAIN=brewmyjob.com` in `.env` and in `wrangler.toml`, then deploy again.
8. **Check:**
   - `make email-worker-logs` in one terminal.
   - In Gmail: Settings → Forwarding and POP/IMAP → **Add a forwarding address** → paste the address from
     BrewMyJob's Mail setup page.
   - The log shows the Gmail confirmation arriving with `dkim … google.com pass`, and the Mail setup page shows
     the code to type into Gmail.

Then create the Gmail filter: from `jobalerts-noreply@linkedin.com OR jobs-noreply@linkedin.com OR naukri.com` →
**Forward it to** your BrewMyJob address.

## Hand-forwarded alerts

Gmail's **Forward** button makes the user the sender, so the API refuses it (`sender_not_allowed`) unless the user
listed that address on Mail setup (**Forward alerts by hand**). Then it's accepted when DKIM passes for the address's
domain, and the parser reads the original sender from the "Forwarded message" block. Its jobs are unverified in the
catalog (see `docs/plan-m9.md`, decision 9).

## If the log shows `dkim: []`

That means Cloudflare's verdict wasn't found in the topmost header, so the API will refuse the email as
`sender_not_allowed`. Look at the headers of a test message: the raw message in Gmail, or a temporary
`console.log` of `headerFields(raw).slice(0, 5)`. Then adjust `src/auth.ts` and its tests.

## Later (milestone 8)

When the API runs on the server, change `API_URL` in `wrangler.toml` to the server's address, deploy again, and
delete the tunnel.
