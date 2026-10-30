import { Effect } from "effect";
import * as Server from "foldkit/experimental/server";

import { init } from "./client/init.js";
import { Flags } from "./client/model.js";
import { view } from "./features/app.js";
import { loadFlags } from "./server/load-flags.js";
import { serverRuntime } from "./server/runtime.js";

export const renderDocument: Server.DocumentRenderer = (application, assets) =>
  Server.renderDocument(application, assets, { lang: application.lang ?? "en" });

const renderPageEffect = Effect.fn("renderPage")(function* renderPageEffect(
  request: Request
) {
  const flags = yield* loadFlags(request);
  const status = flags.page._tag === "NotFound" ? 404 : 200;

  const application = yield* Server.renderToString(
    { Flags, init, routing: {}, view },
    { flags, url: request.url }
  );

  return Server.Rendered(application, {
    headers: { "cache-control": "private, no-store", vary: "cookie" },
    status,
  });
});

// @effect-diagnostics-next-line asyncFunction:off -- Foldkit awaits the Web request boundary.
export const renderPage = async (request: Request): Promise<Server.EntryResult> =>
  await serverRuntime.runPromise(renderPageEffect(request));
