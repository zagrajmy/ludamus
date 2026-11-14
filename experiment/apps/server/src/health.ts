import { Effect } from "effect";
import { HttpRouter, HttpServerResponse } from "effect/http";
import { SqlClient } from "effect/sql/SqlClient";

export const HEALTH_PATH = "/healthz/";

export const healthRoutes = HttpRouter.use(
  Effect.fn("Health.routes")(function* healthRoutes(router) {
    const sql = yield* SqlClient;

    const check = sql`SELECT 1`.pipe(
      Effect.as(HttpServerResponse.jsonUnsafe({ status: "ok" })),
      Effect.catchTag("SqlError", (failure) =>
        Effect.logError("health check failed", failure).pipe(
          Effect.as(
            HttpServerResponse.jsonUnsafe({ status: "error" }, { status: 503 })
          )
        )
      ),
      Effect.map(HttpServerResponse.setHeader("cache-control", "no-store"))
    );

    yield* router.add("GET", HEALTH_PATH, check);
  })
);
