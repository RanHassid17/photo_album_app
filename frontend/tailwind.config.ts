import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["system-ui", "Segoe UI", "Arial", "sans-serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;
