import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { hostname: "tb-static.uber.com" },
      { hostname: "just-eat-prod-eu-res.cloudinary.com" },
      { hostname: "**.deliveroo.com" },
      { hostname: "**.roocdn.com" },
      { hostname: "**.cloudinary.com" },
    ],
  },
};

export default nextConfig;
