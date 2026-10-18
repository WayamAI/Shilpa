import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs on :8000 locally; proxy keeps the browser same-origin.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/v1": "http://127.0.0.1:8000" } },
});
