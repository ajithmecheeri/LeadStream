# syntax=docker/dockerfile:1
# FitFirst web (Next.js standalone). Build context is the REPO ROOT: docker build -f apps/web/Dockerfile .
FROM node:22-alpine AS base
RUN corepack enable
WORKDIR /repo

FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml turbo.json tsconfig.base.json ./
COPY apps/web/package.json apps/web/
COPY packages/api/package.json packages/api/
COPY packages/ui-tokens/package.json packages/ui-tokens/
RUN pnpm install --frozen-lockfile --filter @fitfirst/web...

FROM deps AS build
COPY packages packages
COPY apps/web apps/web
# The web tests type-check the extension's field rules (lib/extension-match.test.ts).
COPY apps/extension apps/extension
# Settings → Browser extension → Download (user, 2026-11-17): the extension as a zip, one folder inside.
RUN apk add --no-cache zip && mkdir -p apps/web/public/downloads /tmp/x  && cp -r apps/extension /tmp/x/brewmyjob-extension && rm -f /tmp/x/brewmyjob-extension/*.md  && cd /tmp/x && zip -qr /repo/apps/web/public/downloads/brewmyjob-extension.zip brewmyjob-extension
# Only used when Caddy isn't in front (Caddy normally routes /api itself).
ARG API_ORIGIN=http://api:8000
ENV API_ORIGIN=$API_ORIGIN NEXT_TELEMETRY_DISABLED=1
RUN pnpm --filter @fitfirst/web build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
RUN addgroup -S app && adduser -S app -G app
COPY --from=build --chown=app:app /repo/apps/web/.next/standalone ./
COPY --from=build --chown=app:app /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=app:app /repo/apps/web/public ./apps/web/public
USER app
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1:3000/sign-in >/dev/null || exit 1
CMD ["node", "apps/web/server.js"]
