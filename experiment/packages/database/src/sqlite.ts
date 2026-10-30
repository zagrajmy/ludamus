import { SqliteClient } from "@effect/sql-sqlite-node";
import { Config, Layer } from "effect";

export const SqliteLive = Layer.unwrap(
  Config.String("DATABASE_PATH").pipe(
    Config.map((filename) =>
      SqliteClient.layer({ busyTimeout: "5 seconds", filename })
    )
  )
);
