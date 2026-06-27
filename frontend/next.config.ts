import type { NextConfig } from "next";

const apiProxy = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async redirects() {
    return [];
  },
  async rewrites() {
    if (!apiProxy) return [];
    return [
      {
        source: "/api/:path*",
        destination: `${apiProxy.replace(/\/$/, "")}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
