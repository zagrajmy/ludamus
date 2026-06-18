import { resolve } from "node:path";

import tailwindcss from "@tailwindcss/vite";
import { defineConfig, type Plugin } from "vite";

// Vite's default HTML hot-update sends {type:"full-reload", path:"<file>"}.
// The Vite client (client.mjs case "full-reload") only reloads when that
// path matches location.pathname. We serve HTML from Django (/events/, …)
// not Vite, so the paths never match and the browser silently ignores the
// signal. Send a custom event handled by src/django-hmr.ts so Django-rendered
// pages reload even when Vite's built-in HTML path matching does not apply.
const djangoTemplateReload = (): Plugin => ({
  name: "django-template-reload",
  handleHotUpdate: {
    order: "pre",
    handler({ file, server }) {
      if (file.endsWith(".html")) {
        server.environments.client.hot.send({
          type: "custom",
          event: "django-template-reload",
        });
        return [];
      }
    },
  },
});

export default defineConfig({
  base: "/static/vite/",
  plugins: [djangoTemplateReload(), tailwindcss()],
  server: {
    host: "0.0.0.0",
    port: Number(process.env.VITE_PORT ?? 5173),
    strictPort: true,
    cors: {
      origin:
        /^https?:\/\/(localhost|127\.0\.0\.1|([a-z0-9-]+\.)+(localhost|local))(:\d+)?$/,
    },
  },
  build: {
    outDir: resolve(__dirname, "../static/vite"),
    emptyOutDir: true,
    manifest: "manifest.json",
    rollupOptions: {
      input: {
        djangoHmr: resolve(__dirname, "src/django-hmr.ts"),
        index: resolve(__dirname, "src/index.css"),
        "encounter-form": resolve(__dirname, "src/encounter-form.ts"),
        "event-print": resolve(__dirname, "src/event-print.ts"),
        confirm: resolve(__dirname, "src/confirm.ts"),
        "info-popover": resolve(__dirname, "src/info-popover.ts"),
        menu: resolve(__dirname, "src/menu.ts"),
        modal: resolve(__dirname, "src/modal.ts"),
        tabs: resolve(__dirname, "src/tabs.ts"),
        timetable: resolve(__dirname, "src/timetable.ts"),
        "session-filters": resolve(__dirname, "src/session-filters.ts"),
        "session-edit": resolve(__dirname, "src/session-edit.ts"),
        "session-card": resolve(__dirname, "src/session-card.ts"),
      },
    },
  },
});
