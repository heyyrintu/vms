import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  skipTrailingSlashRedirect: true,
  async rewrites() {
    const api = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*/` },
      { source: "/admin/:path*", destination: `${api}/admin/:path*/` },
      { source: "/static/:path*", destination: `${api}/static/:path*` },
    ];
  },
};

export default nextConfig;
