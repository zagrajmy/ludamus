import { AppConfig } from "@zagrajmy/core";
import { Effect, FileSystem, Path, Predicate, Result, Schema } from "effect";
import {
  HttpRouter,
  HttpServerRequest,
  HttpServerResponse,
  HttpStaticServer,
} from "effect/http";

import { RequestContext } from "./request-context.js";

export class WebBuildMissing extends Schema.TaggedError<WebBuildMissing>()(
  "WebBuildMissing",
  { cause: Schema.Defect(), location: Schema.String }
) {
  override get message(): string {
    return `The Foldkit build is missing or unreadable at ${this.location}. Run \`pnpm --filter @zagrajmy/web run build\` in experiment/ first.`;
  }
}

const BuildManifest = Schema.Struct({
  client: Schema.String,
  prerendered: Schema.Array(Schema.String),
  schemaVersion: Schema.Literals([1]),
  server: Schema.String,
  serverEntry: Schema.String,
});

type FetchHandler = (request: Request) => Promise<Response>;

const FetchModule = Schema.Struct({
  default: Schema.Struct({
    fetch: Schema.declare((input): input is FetchHandler =>
      Predicate.isFunction(input)
    ),
  }),
});

const HOST_SETTLED_METHODS: ReadonlySet<string> = new Set([
  "CONNECT",
  "TRACE",
  "TRACK",
]);

const ALLOWED_METHODS = "GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS";

const loadBuild = Effect.fn("Web.loadBuild")(function* loadBuild() {
  const fileSystem = yield* FileSystem.FileSystem;
  const path = yield* Path.Path;

  const manifestUrl = yield* Effect.try({
    catch: (cause) =>
      new WebBuildMissing({ cause, location: "@zagrajmy/web/build-manifest" }),
    try: () => import.meta.resolve("@zagrajmy/web/build-manifest"),
  });

  const manifestPath = yield* path.fromFileUrl(new URL(manifestUrl));

  const manifest = yield* fileSystem.readFileString(manifestPath).pipe(
    Effect.flatMap(
      Schema.decodeUnknownEffect(Schema.fromJsonString(BuildManifest))
    ),
    Effect.mapError(
      (cause) => new WebBuildMissing({ cause, location: manifestPath })
    )
  );

  const root = path.resolve(
    path.dirname(manifestPath),
    path.relative(manifest.server, ".")
  );

  const entryPath = path.resolve(root, manifest.server, manifest.serverEntry);
  const entryUrl = yield* path.toFileUrl(entryPath);

  const loaded = yield* Effect.tryPromise({
    catch: (cause) => new WebBuildMissing({ cause, location: entryPath }),
    // oxlint-disable-next-line typescript/promise-function-async -- Effect.tryPromise takes the Promise thunk; an async wrapper would trip the asyncFunction diagnostic.
    try: () => import(entryUrl.href),
  }).pipe(
    Effect.flatMap(Schema.decodeUnknownEffect(FetchModule)),
    Effect.mapError(
      (cause) => new WebBuildMissing({ cause, location: entryPath })
    )
  );

  return {
    clientDirectory: path.resolve(root, manifest.client),
    fetch: loaded.default.fetch,
  };
});

const unknownHostPage = (host: string) =>
  HttpServerResponse.text(`Not found: no sphere is served at ${host}.`, {
    status: 404,
  });

const refusedMethod = HttpServerResponse.empty({
  headers: { allow: ALLOWED_METHODS },
  status: 405,
});

const badRequest = HttpServerResponse.empty({ status: 400 });

export const webRoutes = HttpRouter.use(
  Effect.fn("Web.routes")(function* webRoutes(router) {
    const build = yield* loadBuild();
    const config = yield* AppConfig;
    const context = yield* RequestContext;

    const staticFiles = yield* HttpStaticServer.make({
      index: undefined,
      root: build.clientDirectory,
    });

    const render = Effect.fn("Web.render")(function* render(
      request: HttpServerRequest.HttpServerRequest
    ) {
      const host = request.headers.host ?? config.publicOrigin.host;
      const origin = `${config.publicOrigin.protocol}//${host}`;

      if (!URL.canParse(request.url, origin)) {
        return badRequest;
      }

      const target = new URL(request.url, origin);

      if (target.origin !== new URL(origin).origin) {
        return badRequest;
      }

      const sphere = yield* context.sphere(host).pipe(Effect.result);

      if (Result.isFailure(sphere)) {
        return unknownHostPage(host);
      }

      const signal = yield* Effect.abortSignal;
      const webRequest = yield* HttpServerRequest.toWeb(request, { signal });

      const response = yield* Effect.promise(
        // oxlint-disable-next-line typescript/promise-function-async -- Effect.promise takes the Promise thunk of the Web fetch boundary; an async wrapper would trip the asyncFunction diagnostic.
        () => build.fetch(new Request(target, webRequest))
      );

      return HttpServerResponse.fromWeb(response);
    });

    const handle = (request: HttpServerRequest.HttpServerRequest) => {
      if (HOST_SETTLED_METHODS.has(request.method.toUpperCase())) {
        return Effect.succeed(refusedMethod);
      }

      if (request.method === "GET" || request.method === "HEAD") {
        return staticFiles.pipe(
          Effect.catchTag("HttpServerError", () => render(request))
        );
      }

      return render(request);
    };

    yield* router.add("*", "/*", (request) =>
      handle(request).pipe(Effect.interruptible)
    );
  })
);
