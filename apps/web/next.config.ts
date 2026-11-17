import path from "node:path";
import type { NextConfig } from "next";

// In Docker, Caddy sends /api/* straight to the API. Without Caddy (pnpm dev) Next proxies it,
// so the browser always talks to one origin and the refresh cookie stays first-party.
const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";

const config: NextConfig = {
  output: "standalone",
  // Monorepo: trace workspace packages from the repo root so the standalone build includes them.
  outputFileTracingRoot: path.join(__dirname, "../../"),
  reactStrictMode: true,
  transpilePackages: ["@fitfirst/api", "@fitfirst/ui-tokens"],
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` },
      { source: "/healthz", destination: `${API_ORIGIN}/healthz` },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default config;
