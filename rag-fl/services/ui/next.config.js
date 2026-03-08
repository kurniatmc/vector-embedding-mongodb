/** @type {import('next').NextConfig} */
const nextConfig = {
  // Expose env vars to the browser bundle.
  // With `next dev` (used in Docker), these are read live from process.env at startup.
  // Defaults point to host-exposed ports so the browser can reach backend APIs directly.
  env: {
    NEXT_PUBLIC_RAG_FL_API:
      process.env.NEXT_PUBLIC_RAG_FL_API || "http://localhost:8004",
    NEXT_PUBLIC_INGESTION_API:
      process.env.NEXT_PUBLIC_INGESTION_API || "http://localhost:8001",
    NEXT_PUBLIC_FORCE_MIXED_MODE:
      process.env.NEXT_PUBLIC_FORCE_MIXED_MODE || "",
  },
  // Transpile ESM-only packages so Next.js (CommonJS bundler) can consume them.
  transpilePackages: ["react-markdown", "remark-gfm"],
};

module.exports = nextConfig;
