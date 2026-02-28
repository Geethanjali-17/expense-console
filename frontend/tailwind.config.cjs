/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx,jsx,js}"],
  theme: {
    extend: {
      colors: {
        primary: {
          500: "#6366F1",
          600: "#4F46E5",
          700: "#4338CA",
        },
        accent: {
          500: "#22C55E",
        },
      },
    },
  },
  plugins: [],
};


