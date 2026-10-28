import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // Mirrors `paths` in tsconfig.json; shadcn/ui components import through `@/`.
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  // Tauri prints its own Rust errors; keep Vite from clearing them off the terminal.
  clearScreen: false,
  server: {
    // Must match build.devUrl in src-tauri/tauri.conf.json.
    port: 1420,
    strictPort: true,
    // Rust changes are picked up by `tauri dev` itself; reloading the page for them is noise.
    watch: { ignored: ["**/src-tauri/**"] },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
