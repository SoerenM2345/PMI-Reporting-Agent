/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // The RAG palette used by the decks and dashboards, so the UI and the
        // generated artefacts say the same thing with the same colours.
        rag: {
          green: "#2E7D32",
          amber: "#F9A825",
          red: "#C62828",
          grey: "#757575",
        },
      },
    },
  },
  plugins: [],
};
