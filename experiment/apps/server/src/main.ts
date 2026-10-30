import { createServer } from "node:http";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { NodeHttpServer, NodeRuntime, NodeServices } from "@effect/platform-node";
import { Config, Effect, Layer, Option, Schema } from "effect";
import {
  HttpMiddleware,
  HttpServer,
  HttpServerRequest,
  HttpServerResponse,
  HttpStaticServer,
} from "effect/http";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(here, "../../web");

const BuildManifest = Schema.Struct({
  client: Schema.String,
  prerendered: Schema.Array(Schema.String),
  schemaVersion: Schema.Literals([1]),
  server: Schema.String,
  serverEntry: Schema.String,
});

const FetchModule = Schema.Struct({
  default: Schema.Struct({
    fetch: Schema.declare(
      (input): input is (request: Request) => Promise<Response> =>
        typeof input === "function"
    ),
  }),
});

const loadWeb = Effect.gen(function* loadWeb() {
  const manifestPath = resolve(webRoot, "dist/server/foldkit.build.json");
  const manifest = yield* Effect.tryPromise(async () =>
    (await import("node:fs/promises")).readFile(manifestPath, "utf8")
  ).pipe(Effect.flatMap(Schema.decodeUnknownEffect(Schema.fromJsonString(BuildManifest))));
  const serverEntry = resolve(webRoot, manifest.server, manifest.serverEntry);
  const loaded = yield* Effect.tryPromise(() => import(pathToFileURL(serverEntry).href)).pipe(
    Effect.flatMap(Schema.decodeUnknownEffect(FetchModule))
  );

  return {
    clientDirectory: resolve(webRoot, manifest.client),
    fetch: loaded.default.fetch,
  };
});

const toWebResponse = (response: Response) =>
  Effect.gen(function* toWebResponse() {
    const headers = Object.fromEntries(response.headers.entries());
    const body = response.body === null ? null : yield* Effect.promise(() => response.arrayBuffer());

    return body === null
      ? HttpServerResponse.empty({ headers, status: response.status })
      : HttpServerResponse.uint8Array(new Uint8Array(body), { headers, status: response.status });
  });

const app = Effect.gen(function* app() {
  const web = yield* loadWeb;
  const staticFiles = yield* HttpStaticServer.make({ index: undefined, root: web.clientDirectory });
  const origin = yield* Config.String("PUBLIC_ORIGIN").pipe(Config.withDefault("http://localhost:8000"));

  return HttpServerRequest.HttpServerRequest.use((request) =>
    Effect.gen(function* handle() {
      const url = new URL(request.url, origin);
      const page = Effect.gen(function* page() {
        const signal = yield* Effect.abortSignal;
        const webRequest = yield* HttpServerRequest.toWeb(request, { signal });
        const response = yield* Effect.promise(() => web.fetch(new Request(url, webRequest)));

        return yield* toWebResponse(response);
      });

      if (request.method === "GET" || request.method === "HEAD") {
        return yield* staticFiles.pipe(Effect.catch(() => page));
      }

      return yield* page;
    })
  );
});

const port = Config.Port("PORT").pipe(Config.withDefault(8000));

const httpServer = Layer.unwrap(
  Effect.map(port, (listenPort) =>
    NodeHttpServer.layer(createServer, { port: listenPort })
  )
);

const serverLayer = Layer.unwrap(
  Effect.map(app, (handler) =>
    HttpServer.serve(handler, HttpMiddleware.logger).pipe(HttpServer.withLogAddress)
  )
).pipe(Layer.provide(httpServer), Layer.provide(NodeServices.layer));

NodeRuntime.runMain(Layer.launch(serverLayer));

export { Option };
