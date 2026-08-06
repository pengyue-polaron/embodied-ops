import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import { fileURLToPath } from "node:url"

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    outDir: "../src/embodied_ops/operator_panel/assets",
    emptyOutDir: true,
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        entryFileNames: "panel.js",
        assetFileNames: (asset) =>
          asset.name?.endsWith(".css") ? "panel.css" : "assets/[name]-[hash][extname]",
      },
    },
  },
})
