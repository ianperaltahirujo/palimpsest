import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react()],
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
