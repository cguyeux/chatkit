import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Minimal server bundle for Docker / Serverless Containers.
  output: "standalone",
  // The root page was served with Cache-Control: s-maxage=31536000 (1 year,
  // Next.js's default for a fully static page) -- confirmed live 2026-09-15:
  // a redeploy is invisible to a client stuck behind that edge cache even
  // after a hard refresh, since the caching happens upstream of the
  // browser. Content-hashed assets under /_next/static/ are left alone
  // (safe to cache forever, a new build gets new hashes automatically).
  async headers() {
    return [
      {
        source: "/",
        headers: [{ key: "Cache-Control", value: "no-store, must-revalidate" }],
      },
    ];
  },
};

export default nextConfig;
