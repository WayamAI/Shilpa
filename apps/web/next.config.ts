import type { NextConfig } from "next";

/** FastAPI backend. The browser only ever talks to this Next.js origin. */
const API_ORIGIN = process.env.SHILPA_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // The dev indicator defaults to bottom-left, where it covers the sidebar's theme and sign-out controls.
  devIndicators: { position: "bottom-right" },
  async rewrites() {
    // /v1 is a URL proxy to the Shilpa API (uploads, SSE and downloads included).
    // proxy.ts excludes /v1 from its matcher so request bodies are never buffered there.
    return [{ source: "/v1/:path*", destination: `${API_ORIGIN}/v1/:path*` }];
  },
};

export default nextConfig;
