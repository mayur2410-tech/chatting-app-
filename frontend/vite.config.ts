import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 5173,
    // Same-origin API in development: the browser talks only to Vite, which forwards /api.
    // 127.0.0.1 (not localhost) avoids slow IPv6 fallbacks on Windows.
    proxy: {
      // ws: true also forwards the /api/ws/chat WebSocket upgrade (with the browser's Origin and cookie).
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false, ws: true },
    },
  },
  build: {
    sourcemap: false,
  },
});
