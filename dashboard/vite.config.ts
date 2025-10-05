import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import csp from "vite-plugin-csp-guard";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    csp({
      algorithm: "sha256",
      dev: {
        run: true,
      },
      policy: {
        "default-src": [
          "'self'",
          "'unsafe-inline'",
          "'unsafe-eval'",
          "http:",
          "https:",
          "data:",
          "blob:",
        ],
        "connect-src": [
          "'self'",
          "ws:",
          "ws://localhost:8000",
          "wss://localhost:8000",
          "http://localhost:8000",
          "https://localhost:8000",
        ],
        "script-src": ["'self'", "'unsafe-inline'", "'unsafe-eval'"],
        "style-src": ["'self'", "'unsafe-inline'"],
        "img-src": ["'self'", "data:", "https:"],
      },
    }),
  ],
  define: {
    global: "globalThis",
  },
});
