/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Proxy config is handled in app/api/proxy route handler

  // Enable standalone output for Docker multi-stage builds.
  // Creates a self-contained .next/standalone folder with a minimal server.js.
  output: "standalone",
};

export default nextConfig;
