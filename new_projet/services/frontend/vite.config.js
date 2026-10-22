import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En développement (npm run dev), les appels /api sont relayés vers la plateforme lancée par Docker.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: { "/api": "http://127.0.0.1:8088" },
  },
});
