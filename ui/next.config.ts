import type { NextConfig } from "next";

/**
 * Next.js 16 config (App Router, React 19). The UI is a customer-facing shell over the
 * FastAPI RAG backend: Clerk auth, Vercel AI SDK useChat, citation chips, tenant switcher.
 *
 * The /api/chat route proxies to BACKEND_URL (the FastAPI service) and translates the
 * backend's custom SSE (event: citations/token/done) into the AI SDK UIMessage wire protocol.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Standalone output for the minimal multi-stage Docker image (.next/standalone server).
  output: "standalone",
};

export default nextConfig;