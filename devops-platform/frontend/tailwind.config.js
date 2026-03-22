/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        cream: "#F5EFE6",
        primary: "#E8832A",
        ink: "#1a1208",
      },
    },
  },
  plugins: [],
};
