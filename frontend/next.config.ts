import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  devIndicators: false,
  output: "standalone",
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
  async redirects() {
    return [
      {
        source: "/inbox",
        destination: "/",
        permanent: false,
      },
      {
        source: "/runs",
        destination: "/sources",
        permanent: false,
      },
    ]
  },
}

export default nextConfig
