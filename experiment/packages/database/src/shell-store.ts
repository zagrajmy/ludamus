import { SphereChromeRow, ViewerChromeRow } from "@zagrajmy/core/feed";
import { ShellStore } from "@zagrajmy/core/ports/shell-store";
import { Effect, Layer, Option } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { decodeRows } from "./rows.js";

export const ShellStoreLive = Layer.effect(
  ShellStore,
  Effect.gen(function* makeShellStore() {
    const sql = yield* SqlClient;

    const sphereColumns = sql`
      sphere.id AS id, sphere.name AS name, sphere.logo AS logo,
      sphere.encounters_policy AS encountersPolicy, sphere.site_id AS siteId,
      django_site.domain AS domain
    `;

    return ShellStore.of({
      sphereByDomain: (domain) =>
        sql`
          SELECT ${sphereColumns}
          FROM sphere JOIN django_site ON django_site.id = sphere.site_id
          WHERE django_site.domain = ${domain}
          LIMIT 1
        `.pipe(
          decodeRows("ShellStore.sphereByDomain", SphereChromeRow),
          Effect.map((rows) => Option.fromNullishOr(rows[0]))
        ),
      sphereBySite: (siteId) =>
        sql`
          SELECT ${sphereColumns}
          FROM sphere JOIN django_site ON django_site.id = sphere.site_id
          WHERE sphere.site_id = ${siteId}
          LIMIT 1
        `.pipe(
          decodeRows("ShellStore.sphereBySite", SphereChromeRow),
          Effect.map((rows) => Option.fromNullishOr(rows[0]))
        ),
      viewer: ({ sphereId, userId }) =>
        sql`
          SELECT user.id AS id, user.name AS name, user.username AS username,
                 user.email AS email, user.avatar_url AS avatarUrl,
                 user.use_gravatar AS useGravatar, user.is_superuser AS isSuperuser,
                 (
                   SELECT role FROM sphere_managers
                   WHERE sphere_managers.sphere_id = ${sphereId} AND sphere_managers.user_id = user.id
                   LIMIT 1
                 ) AS sphereRole
          FROM user WHERE user.id = ${userId} AND user.is_active = 1
          LIMIT 1
        `.pipe(
          decodeRows("ShellStore.viewer", ViewerChromeRow),
          Effect.map((rows) => Option.fromNullishOr(rows[0]))
        ),
    });
  })
);
