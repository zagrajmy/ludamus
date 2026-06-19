import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";

const rootDir = fileURLToPath(new URL(".", import.meta.url));

// Vite's default HTML hot-update sends {type:"full-reload", path:"<file>"}.
// The Vite client (client.mjs case "full-reload") only reloads when that
// path matches location.pathname. We serve HTML from Django (/events/, …)
// not Vite, so the paths never match and the browser silently ignores the
// signal. Send a custom event handled by src/django-hmr.ts so Django-rendered
// pages reload even when Vite's built-in HTML path matching does not apply.
const djangoTemplateReload = (): Plugin => ({
  handleHotUpdate: {
    handler({ file, server }) {
      if (file.endsWith(".html")) {
        server.environments.client.hot.send({
          event: "django-template-reload",
          type: "custom",
        });
        return [];
      }
    },
    order: "pre",
  },
  name: "django-template-reload",
});

export default defineConfig({
  base: "/static/vite/",
  build: {
    emptyOutDir: true,
    manifest: "manifest.json",
    outDir: resolve(rootDir, "../static/vite"),
    rollupOptions: {
      input: {
        confirm: resolve(rootDir, "src/confirm.ts"),
        djangoHmr: resolve(rootDir, "src/django-hmr.ts"),
        "encounter-form": resolve(rootDir, "src/encounter-form.ts"),
        "event-print": resolve(rootDir, "src/event-print.ts"),
        index: resolve(rootDir, "src/index.css"),
        "info-popover": resolve(rootDir, "src/info-popover.ts"),
        menu: resolve(rootDir, "src/menu.ts"),
        modal: resolve(rootDir, "src/modal.ts"),
        "session-card": resolve(rootDir, "src/session-card.ts"),
        "session-edit": resolve(rootDir, "src/session-edit.ts"),
        "session-filters": resolve(rootDir, "src/session-filters.ts"),
        tabs: resolve(rootDir, "src/tabs.ts"),
        timetable: resolve(rootDir, "src/timetable.ts"),
      },
    },
  },
  plugins: [djangoTemplateReload(), tailwindcss()],
  server: {
    cors: {
      origin:
        /^https?:\/\/(localhost|127\.0\.0\.1|([a-z0-9-]+\.)+(localhost|local))(:\d+)?$/,
    },
    host: "0.0.0.0",
    port: Number(process.env.VITE_PORT ?? 5173),
    strictPort: true,
  },
});
