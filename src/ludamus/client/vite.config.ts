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
        "app-scroll": resolve(rootDir, "src/app-scroll.ts"),
        "bulk-status": resolve(rootDir, "src/bulk-status.ts"),
        confirm: resolve(rootDir, "src/confirm.ts"),
        copy: resolve(rootDir, "src/copy.ts"),
        "design-page": resolve(rootDir, "src/design-page.ts"),
        djangoHmr: resolve(rootDir, "src/django-hmr.ts"),
        "encounter-form": resolve(rootDir, "src/encounter-form.ts"),
        "enroll-preview": resolve(rootDir, "src/enroll-preview.ts"),
        "event-print": resolve(rootDir, "src/event-print.ts"),
        "event-timeline": resolve(rootDir, "src/event-timeline.ts"),
        "filter-autosubmit": resolve(rootDir, "src/filter-autosubmit.ts"),
        flash: resolve(rootDir, "src/flash.ts"),
        "import-recipe": resolve(rootDir, "src/import-recipe.ts"),
        index: resolve(rootDir, "src/index.css"),
        "info-popover": resolve(rootDir, "src/info-popover.ts"),
        menu: resolve(rootDir, "src/menu.ts"),
        modal: resolve(rootDir, "src/modal.ts"),
        "panel-columns": resolve(rootDir, "src/panel-columns.ts"),
        "room-lanes": resolve(rootDir, "src/room-lanes.ts"),
        "session-bookmarks": resolve(rootDir, "src/session-bookmarks.ts"),
        "session-card": resolve(rootDir, "src/session-card.ts"),
        "session-edit": resolve(rootDir, "src/session-edit.ts"),
        "session-filters": resolve(rootDir, "src/session-filters.ts"),
        sound: resolve(rootDir, "src/sound.ts"),
        "space-tree": resolve(rootDir, "src/space-tree.ts"),
        stepper: resolve(rootDir, "src/stepper.ts"),
        "tab-scroll": resolve(rootDir, "src/tab-scroll.ts"),
        tabs: resolve(rootDir, "src/tabs.ts"),
        timetable: resolve(rootDir, "src/timetable.ts"),
      },
    },
  },
  plugins: [djangoTemplateReload(), tailwindcss()],
  server: {
    cors: {
      origin: /^https?:\/\/(localhost|127\.0\.0\.1|([a-z0-9-]+\.)+(localhost|local))(:\d+)?$/,
    },
    host: "0.0.0.0",
    port: Number(process.env.VITE_PORT ?? 5173),
    strictPort: true,
  },
});
