import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// A relative base makes the built site deployment-agnostic: it works at a domain
// root and under a project sub-path (e.g. https://<user>.github.io/balyoo/) without
// a rebuild, which is exactly what the "one build, many deployments" design needs.
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    // In dev the UI talks to a live `collections serve` (see README); proxying the
    // API here avoids any CORS configuration on the Python side.
    proxy: {
      "/collections": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
});
