/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",  // Jinja templates
    "./**/*.py",              // D-05: Python HTMLResponse fragments (Pitfall 10 mitigation)
  ],
  safelist: [
    "text-green-400",  // dashboard.py inline status
    "text-red-400",    // dashboard.py inline status
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Preserve v1.0 palette from templates/base.html:15, 22
        dark: { 700: "#252542", 800: "#1a1a2e", 900: "#0f0f1a" },
      },
    },
  },
};
