import { Sphere, StoreError } from "@zagrajmy/core";
import { Context, Effect, Layer, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { decodeRows } from "./rows.js";

export class SphereStore extends Context.Service<
  SphereStore,
  {
    readonly byDomain: (
      domain: string
    ) => Effect.Effect<Option.Option<Sphere>, StoreError>;
  }
>()("@zagrajmy/database/SphereStore") {}

export const SphereStoreLive = Layer.effect(
  SphereStore,
  Effect.gen(function* makeSphereStore() {
    const sql = yield* SqlClient;

    return SphereStore.of({
      byDomain: (domain) =>
        sql`
          SELECT sphere.id AS id, sphere.name AS name, django_site.domain AS domain
          FROM sphere JOIN django_site ON django_site.id = sphere.site_id
          WHERE django_site.domain = ${domain}
        `.pipe(
          decodeRows("SphereStore.byDomain", Sphere),
          Effect.map((rows) => Option.fromNullishOr(rows[0]))
        ),
    });
  })
);

export const SphereRow = Sphere;
export type SphereRow = typeof Sphere.Type;
export const SphereRowSchema = Schema.Struct(Sphere.fields);
