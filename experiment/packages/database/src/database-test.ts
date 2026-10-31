import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { SqliteClient } from "@effect/sql-sqlite-node";
import { Effect, Layer } from "effect";

import { StoresLive } from "./stores.js";

export const SEEDED_DATABASE_PATH = fileURLToPath(
  new URL("../../../../dev.e2e.sqlite3", import.meta.url)
);

const snapshot = (source: string) =>
  Effect.acquireRelease(
    Effect.sync(() => mkdtempSync(path.join(tmpdir(), "zagrajmy-db-"))),
    (directory) =>
      Effect.sync(() => {
        rmSync(directory, { force: true, recursive: true });
      })
  ).pipe(
    Effect.flatMap((directory) => {
      const target = path.join(directory, "snapshot.sqlite3");

      return SqliteClient.SqliteClient.pipe(
        Effect.flatMap((client) => client.backup(target)),
        Effect.provide(
          SqliteClient.layer({ filename: source, readonly: true })
        ),
        Effect.as(target)
      );
    })
  );

export const databaseSnapshotLayer = (source: string = SEEDED_DATABASE_PATH) =>
  Layer.unwrap(
    snapshot(source).pipe(
      Effect.map((filename) =>
        SqliteClient.layer({ busyTimeout: "5 seconds", filename })
      )
    )
  );

export const DatabaseTest = StoresLive.pipe(
  Layer.provideMerge(databaseSnapshotLayer())
);
