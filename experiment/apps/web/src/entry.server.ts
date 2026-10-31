import { Cause, Effect } from "effect";
import * as Server from "foldkit/experimental/server";

import { init } from "./client/init.js";
import { Flags } from "./client/model.js";
import { view } from "./features/app.js";
import { withShellHead } from "./server/document.js";
import {
  clearedFlashCookie,
  flashCookieHeader,
  hasFlashCookie,
} from "./server/flash.js";
import {
  isProposeStepPath,
  respondToProposeStep,
} from "./server/pages/propose.js";
import { loadRequestContext } from "./server/request-context.js";
import { route } from "./server/router.js";
import { serverRuntime } from "./server/runtime.js";
import { loadShellFlags } from "./server/shell.js";

export { renderDocument } from "./server/document.js";

export const prerenderPaths: readonly string[] = [];

const pageHeaders = { "cache-control": "private, no-store", vary: "cookie" };

const plain = (status: number, body: string) =>
  Server.Responded(
    new Response(body, {
      headers: { "content-type": "text/plain; charset=utf-8" },
      status,
    })
  );

const renderPageEffect = Effect.fn("renderPage")(
  function* renderPageEffect(request: Request) {
    if (
      request.method === "POST" &&
      isProposeStepPath(new URL(request.url).pathname)
    ) {
      return Server.Responded(
        yield* respondToProposeStep(yield* loadRequestContext(request))
      );
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      return Server.Responded(
        new Response(null, { headers: { allow: "GET, HEAD" }, status: 405 })
      );
    }

    const context = yield* loadRequestContext(request);
    const routed = yield* route(context);

    if (routed._tag === "Redirect") {
      const headers = new Headers({ location: routed.location });

      if (routed.flashes !== undefined && routed.flashes.length > 0) {
        headers.append("set-cookie", flashCookieHeader(routed.flashes));
      }

      return Server.Responded(
        new Response(null, { headers, status: routed.status })
      );
    }

    const flags: Flags = {
      page: routed.flags,
      shell: yield* loadShellFlags(context),
    };

    const application = yield* Server.renderToString(
      { Flags, init, routing: {}, view },
      { flags, url: request.url }
    );

    return Server.Rendered(withShellHead(application, flags), {
      headers: hasFlashCookie(request)
        ? { ...pageHeaders, "set-cookie": clearedFlashCookie }
        : pageHeaders,
      status: routed.status,
    });
  },
  Effect.catchTag("UnknownSphere", (error) =>
    Effect.succeed(plain(404, error.message))
  )
);

const safely = (request: Request) =>
  renderPageEffect(request).pipe(
    Effect.catchCause((cause) =>
      Effect.logError("renderPage failed", Cause.pretty(cause)).pipe(
        Effect.as(plain(500, "Something went wrong on our side."))
      )
    )
  );

// @effect-diagnostics-next-line asyncFunction:off -- Foldkit awaits the Web request boundary.
export const renderPage = async (
  request: Request
): Promise<Server.EntryResult> =>
  await serverRuntime.runPromise(safely(request));
