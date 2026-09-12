import type { NextConfig } from "next";

// Keep dev and production build artifacts separate so running `next build`
// cannot invalidate an active local development server.
const nextConfig: NextConfig = {
  output: "standalone",
  distDir: process.env.NODE_ENV === "production" ? ".next" : ".next-dev",
};
export default nextConfig;
