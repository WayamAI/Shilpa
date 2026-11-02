import type { NextConfig } from "next";

/**
 * FastAPI backend. The browser only ever talks to this Next.js origin.
 * Next 16 serialises rewrites at build time (routes-manifest.json, server.js), so this is a build-time value.
 * The Dockerfile builds with a placeholder origin and docker-entrypoint.sh swaps in the runtime
 * SHILPA_API_ORIGIN before `node server.js`, so one image serves every environment.
 */
const API_ORIGIN = process.env.SHILPA_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Self-contained server (.next/standalone/server.js) for the container image. See docs/azure/containers.md.
  output: "standalone",
  // The dev indicator defaults to bottom-left, where it covers the sidebar's theme and sign-out controls.
  devIndicators: { position: "bottom-right" },
  async rewrites() {
    // /v1 is a URL proxy to the Shilpa API (uploads, SSE and downloads included).
    // proxy.ts excludes /v1 from its matcher so request bodies are never buffered there.
    return [{ source: "/v1/:path*", destination: `${API_ORIGIN}/v1/:path*` }];
  },
};

export default nextConfig;
