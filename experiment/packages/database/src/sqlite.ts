import { SqliteClient } from "@effect/sql-sqlite-node";
import { AppConfig } from "@zagrajmy/core";
import { Effect, Layer } from "effect";

export const SqliteLive = Layer.unwrap(
  Effect.gen(function* sqliteFromConfig() {
    const { databasePath } = yield* AppConfig;

    return SqliteClient.layer({
      busyTimeout: "5 seconds",
      filename: databasePath,
    });
  })
);
