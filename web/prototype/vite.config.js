import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    proxy: {
      // Target matches cli.py's `palimpsest serve --port` default (8765).
      // Run with a non-default port via `VITE_API_BASE=http://localhost:PORT
      // npm run dev` instead (see web/prototype/README.md) -- api.js then
      // builds absolute URLs that bypass this proxy entirely, so the two
      // mechanisms never conflict.
      //
      // changeOrigin: false (the default) keeps the forwarded Host header
      // as localhost:5173 -- server/security.py's OriginCheckMiddleware
      // derives the expected origin from the request's OWN Host header,
      // so this makes the dev server same-origin from the middleware's
      // point of view with no --dev-origin allowlist entry needed. Setting
      // changeOrigin: true here would make every mutating request 403.
      "/api": { target: "http://127.0.0.1:8765" },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // The edit surface (TipTap + @mantine/tiptap) is only needed once
        // a user actually opens Edit mode -- see edit/EditSurface.jsx's
        // lazy import in CompareStage.jsx. Splitting it into its own
        // chunk here means the initial bundle (everything through
        // Overview -> Results) doesn't pay for an editor most sessions
        // may never open. Vite 8's bundler (rolldown) requires the
        // function form -- the classic Rollup object-map shorthand
        // throws "manualChunks is not a function" here.
        manualChunks(id) {
          if (id.includes("node_modules/@tiptap") || id.includes("node_modules/@mantine/tiptap")) {
            return "tiptap-editor";
          }
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.js"],
    globals: false,
  },
});
