import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

// The board app: a React client in client/, built into dist/, which the
// Worker serves (wrangler.json "assets"). `aube run dev` serves the client
// here with hot reload and sends the rooms API and its socket on to the
// Worker that `aube run dev:worker` runs.

const WORKER_DEV_PORT = 8789;

export default defineConfig({
  build: {
    // NOTE: tldraw's fonts and translations stay files: the board's
    // Content-Security-Policy allows no data: fonts and no host but its own.
    assetsInlineLimit: (file) => (file.includes("@tldraw/assets") ? false : undefined),
    emptyOutDir: true,
    outDir: fileURLToPath(new URL("dist", import.meta.url)),
    sourcemap: true,
  },
  define: {
    // Where Django runs; the deploy sets https://<ROOT_DOMAIN>.
    __APP_ORIGIN__: JSON.stringify(process.env.APP_ORIGIN ?? "http://localhost:8000"),
    // Public by design: tldraw ties it to the board's domain.
    __TLDRAW_LICENSE_KEY__: JSON.stringify(process.env.TLDRAW_LICENSE_KEY ?? ""),
  },
  // NOTE: the dependency pre-bundler cannot follow @tldraw/assets' `?url`
  // imports; Vite serves the package as it is instead.
  optimizeDeps: { exclude: ["@tldraw/assets"] },
  plugins: [tailwindcss()],
  root: fileURLToPath(new URL("client", import.meta.url)),
  server: {
    port: 8788,
    proxy: { "/rooms": { target: `http://localhost:${WORKER_DEV_PORT}`, ws: true } },
    strictPort: true,
  },
});
