import { LandingConventionRow, LandingStatsRow } from "@zagrajmy/core/feed";
import { LandingStore } from "@zagrajmy/core/ports/landing-store";
import { StoreError } from "@zagrajmy/core/ports/store-error";
import { Effect, Layer } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { decodeRows } from "./rows.js";

export const LandingStoreLive = Layer.effect(
  LandingStore,
  Effect.gen(function* makeLandingStore() {
    const sql = yield* SqlClient;

    return LandingStore.of({
      conventions: ({ domains, now }) =>
        domains.length === 0
          ? Effect.succeed([])
          : sql`
              SELECT sphere.name AS name, django_site.domain AS domain,
                     newest.slug AS eventSlug, newest.cover_image AS coverImage
              FROM sphere
              JOIN django_site ON django_site.id = sphere.site_id
              JOIN event newest ON newest.id = (
                SELECT event.id FROM event
                WHERE event.sphere_id = sphere.id
                  AND event.publication_time IS NOT NULL
                  AND event.publication_time <= ${now}
                  AND event.visibility = 'public'
                ORDER BY event.start_time DESC
                LIMIT 1
              )
              WHERE sphere.visibility = 'public' AND django_site.domain IN ${sql.in(domains)}
              LIMIT ${domains.length}
            `.pipe(
              decodeRows("LandingStore.conventions", LandingConventionRow)
            ),
      stats: sql`
        SELECT (SELECT COUNT(*) FROM event) AS events,
               (SELECT COUNT(*) FROM session WHERE deleted_at IS NULL) AS sessions
      `.pipe(
        decodeRows("LandingStore.stats", LandingStatsRow),
        Effect.flatMap((rows) =>
          rows[0] === undefined
            ? Effect.fail(
                new StoreError({
                  operation: "LandingStore.stats",
                  reason: "no row",
                })
              )
            : Effect.succeed(rows[0])
        )
      ),
    });
  })
);
