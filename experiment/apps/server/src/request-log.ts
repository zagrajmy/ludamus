import { Cause, Clock, Effect, Exit } from "effect";
import { HttpServerError, HttpServerRequest } from "effect/http";
import type { HttpServerResponse } from "effect/http";

const SERVER_ERROR = 500;

const pathOf = (url: string) => url.split("?")[0] ?? url;

export const logRequests = <E, R>(
  app: Effect.Effect<HttpServerResponse.HttpServerResponse, E, R>
) =>
  Effect.gen(function* logRequest() {
    const request = yield* HttpServerRequest.HttpServerRequest;
    const started = yield* Clock.currentTimeMillis;
    const exit = yield* Effect.exit(app);
    const durationMs = (yield* Clock.currentTimeMillis) - started;

    const fields = {
      durationMs,
      method: request.method,
      path: pathOf(request.url),
    };

    if (Exit.isSuccess(exit)) {
      const { status } = exit.value;
      const line = status >= SERVER_ERROR ? Effect.logWarning : Effect.logInfo;

      yield* line("request").pipe(Effect.annotateLogs({ ...fields, status }));

      return yield* exit;
    }

    const [response] = yield* HttpServerError.causeResponse(exit.cause);

    if (!Cause.hasInterruptsOnly(exit.cause)) {
      yield* Effect.logError("request failed", exit.cause).pipe(
        Effect.annotateLogs({ ...fields, status: response.status })
      );
    }

    return yield* exit;
  });
