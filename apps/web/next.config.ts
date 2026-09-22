import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // Production uses the deployment edge; readiness stays on the private network.
    if (process.env.NODE_ENV !== "development") return [];
    return [
      { source: "/v1/:path*", destination: "http://127.0.0.1:8000/v1/:path*" },
      {
        source: "/health/:path*",
        destination: "http://127.0.0.1:8000/health/:path*",
      },
    ];
  },
};

export default nextConfig;
