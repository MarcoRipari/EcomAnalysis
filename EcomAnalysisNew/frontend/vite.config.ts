import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy /api sulla FastAPI locale (porta 8001).
// Produzione: nginx servira le statiche (dist/) e proxera /api sullo stesso host.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8001", changeOrigin: true },
    },
  },
});