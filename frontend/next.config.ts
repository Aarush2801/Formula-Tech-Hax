import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the workspace root. Without this, Next walks up past the project and
  // picks up an unrelated lockfile in the home directory.
  turbopack: { root: __dirname },
};

export default nextConfig;
