import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      colors: {
        accent: {
          DEFAULT: "#FF5C28",
          hover:   "#E64A1A",
          subtle:  "#FFF1EB",
        },
        score: {
          low:  "#DC2626",
          mid:  "#F59E0B",
          high: "#16A34A",
        },
      },
      fontSize: {
        display: ["clamp(2.5rem,6vw,4.5rem)", { lineHeight: "1.05", letterSpacing: "-0.02em" }],
      },
      maxWidth: {
        content: "1120px",
      },
    },
  },
  plugins: [],
};

export default config;
