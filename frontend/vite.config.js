import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // `npm run dev` serves the UI on :5173 and forwards the API to uvicorn on :8000,
    // so the frontend hot-reloads without a rebuild of the Python side.
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  test: {
    // jsdom rather than a headless browser: what is worth testing here is
    // component *state*, and the composer's attachment bug was a state-timing
    // bug that only a component test can pin. Real drag-and-drop and a real
    // AbortController would need Playwright; that is a different tool for a
    // different question.
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.js",
    include: ["src/**/*.test.{js,jsx}"],
  },
});
