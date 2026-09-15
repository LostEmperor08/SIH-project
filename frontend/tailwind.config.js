/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#0a0e17", 900: "#0f1420", 800: "#161d2e", 700: "#1f2940", 600: "#2a3654" },
        accent: { DEFAULT: "#22d3ee", dim: "#0e7490" },
      },
      fontFamily: { mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"] },
    },
  },
  plugins: [],
};
