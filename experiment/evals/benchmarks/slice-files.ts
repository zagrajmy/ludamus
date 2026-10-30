import type { CodeArea } from "./code-metrics.ts";

export const sliceAreas: ReadonlyArray<CodeArea> = [
  {
    label: "whole application (all source, templates, client; tests excluded)",
    new: ["experiment/apps/*/src/**/*.{ts,css}", "experiment/packages/{core,database,auth,i18n}/src/**/*.ts"],
    old: ["src/ludamus/**/*.py", "src/ludamus/templates/**/*.html", "src/ludamus/client/src/**/*.{ts,css}"],
  },
  {
    label: "events feed page",
    new: ["experiment/apps/web/src/features/events-feed/**/*.ts", "experiment/apps/web/src/server/pages/events-feed.ts"],
    old: [
      "src/ludamus/gates/web/django/events.py",
      "src/ludamus/templates/index.html",
      "src/ludamus/templates/components/feed_grid.html",
      "src/ludamus/templates/components/event_card.html",
      "src/ludamus/templates/components/encounter_card.html",
      "src/ludamus/templates/components/feed_cover.html",
      "src/ludamus/templates/components/feed_tag.html",
    ],
  },
];
