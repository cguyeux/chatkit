import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Minimal server bundle for Docker / Serverless Containers.
  output: "standalone",
};

export default nextConfig;
