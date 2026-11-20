/// <reference types="vitest/config" />
// The web client (ADR-0067): a static app, served by the API process at `/`.
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // Installable on phones and computers (UX-001); the service worker caches
    // only the app's own files and never the API, and shows notifications (UX-004, ADR-0101).
    VitePWA({
      registerType: "autoUpdate",
      strategies: "injectManifest",
      srcDir: "src/sw",
      filename: "sw.ts",
      includeAssets: ["icon.svg", "apple-touch-icon.png"],
      manifest: {
        name: "Sibillo",
        short_name: "Sibillo",
        description: "A private assistant for the household",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#faf8f5",
        theme_color: "#faf8f5",
        // Other apps share text, links and files into a new chat (UX-006, ADR-0102).
        share_target: {
          action: "/share",
          method: "POST",
          enctype: "multipart/form-data",
          params: { title: "title", text: "text", url: "url", files: [{ name: "files", accept: ["*/*"] }] },
        },
        icons: [
          { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      injectManifest: {
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        maximumFileSizeToCacheInBytes: 8 * 1024 * 1024,
      },
    }),
  ],
  build: { outDir: "dist", sourcemap: false },
  // `pnpm vite` serves the app against an API on the default published port.
  // The unit tests live in tests/web, outside the app (ADR-0067).
  server: { proxy: { "/v1": "http://127.0.0.1:8080" }, fs: { allow: [".", "../../tests/web"] } },
  test: { dir: "../../tests/web/unit", environment: "jsdom" },
});
