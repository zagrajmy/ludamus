// @effect-diagnostics-next-line nodeBuiltinImport:off -- NodeHttpServer.layer takes a node:http server factory; nothing in Effect wraps it.
import { createServer } from "node:http";

import {
  NodeHttpServer,
  NodeRuntime,
  NodeServices,
} from "@effect/platform-node";
import { SessionResolverLive } from "@zagrajmy/auth";
import { AppConfig, mailDirectory } from "@zagrajmy/core";
import { DatabaseLive, fileMailOutbox } from "@zagrajmy/database";
import { Effect, FileSystem, Layer, Logger, Option, Schema } from "effect";
import { HttpRouter } from "effect/http";

import { healthRoutes } from "./health.js";
import { gateMcp } from "./mcp-gate.js";
import { mediaRoutes } from "./media.js";
import { RequestContext } from "./request-context.js";
import { logRequests } from "./request-log.js";
import { surfaces } from "./surfaces.js";
import { webRoutes } from "./web.js";

export class DatabaseMissing extends Schema.TaggedError<DatabaseMissing>()(
  "DatabaseMissing",
  { path: Schema.String }
) {
  override get message(): string {
    return `DATABASE_PATH ${this.path} does not exist. Seed it with \`mise run test:e2e:prep\` from the repo root.`;
  }
}

const requireDatabase = Effect.fn("Server.requireDatabase")(
  function* requireDatabase() {
    const { databasePath } = yield* AppConfig;
    const fileSystem = yield* FileSystem.FileSystem;

    if (!(yield* fileSystem.exists(databasePath))) {
      yield* new DatabaseMissing({ path: databasePath });
    }
  }
);

const DatabaseFileLive = Layer.effectDiscard(requireDatabase());

const MailOutboxLive = Layer.unwrap(
  Effect.gen(function* mailOutboxFromConfig() {
    return Option.match(mailDirectory(yield* AppConfig), {
      onNone: () => Layer.empty,
      onSome: fileMailOutbox,
    });
  })
);

const ServicesLive = RequestContext.layer.pipe(
  Layer.provideMerge(MailOutboxLive),
  Layer.provideMerge(SessionResolverLive),
  Layer.provideMerge(DatabaseLive),
  Layer.provideMerge(DatabaseFileLive),
  Layer.provideMerge(AppConfig.layer),
  Layer.provideMerge(NodeServices.layer)
);

const ServerLive = Layer.unwrap(
  Effect.gen(function* serverFor() {
    const config = yield* AppConfig;
    const gate = gateMcp(config.mcpToken);

    return HttpRouter.serve(Layer.mergeAll(surfaces, healthRoutes, mediaRoutes, webRoutes), {
      disableLogger: true,
      middleware: (app) => logRequests(gate(app)),
    }).pipe(
      Layer.provide(NodeHttpServer.layer(createServer, { port: config.port }))
    );
  })
);

const MainLive = ServerLive.pipe(
  Layer.provide(ServicesLive),
  Layer.provide(Logger.layer([Logger.consoleJson]))
);

NodeRuntime.runMain(Layer.launch(MainLive));
