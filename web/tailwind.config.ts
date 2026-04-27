import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",   // toggle dark-mode by adding `dark` class to <html>
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      animation: {
        "pulse-slow": "pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "spin-slow":  "spin 3s linear infinite",
      },
      colors: {
        // Workspace surface palette — referenced via Tailwind arbitrary syntax.
        // Light: warm cream / ivory.   Dark: deep navy.
        ws: {
          bg:       "#fafaf7",   // light app background (cream)
          panel:    "#ffffff",   // light panel surface
          subtle:   "#f4f3ee",   // light hover/subtle surface
          border:   "#e8e6df",   // light border
          dark: {
            bg:     "#0a0f1e",
            panel:  "#0d1526",
            subtle: "#111c35",
            border: "#1e293b",
          },
        },
      },
    },
  },
  plugins: [],
};

export default config;
