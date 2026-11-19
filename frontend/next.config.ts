import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The floating dev indicator covers table rows and charts in this dense UI.
  devIndicators: false,
  // Forward API calls to the backend so only the frontend port needs to be shared (e.g. VS Code port forwarding).
  async rewrites() {
    return [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }];
  },
  allowedDevOrigins: ["*.devtunnels.ms"],
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
