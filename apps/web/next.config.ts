import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/v1/:path*", destination: "http://127.0.0.1:8000/v1/:path*" },
      { source: "/health/:path*", destination: "http://127.0.0.1:8000/health/:path*" },
    ];
  },
};

export default nextConfig;
