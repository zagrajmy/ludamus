// @effect-diagnostics-next-line nodeBuiltinImport:off -- Constant-time comparison of the bearer token needs node:crypto; Effect has no timing-safe equality.
import { createHash, timingSafeEqual } from "node:crypto";

import { Effect, Option, Redacted } from "effect";
import { HttpServerRequest, HttpServerResponse } from "effect/http";

export const MCP_PATH = "/mcp";

const digest = (value: string) => createHash("sha256").update(value).digest();

const bearerOf = (authorization: string | undefined) =>
  Option.fromNullishOr(
    /^Bearer\s+(?<token>\S+)$/iu.exec(authorization ?? "")?.groups?.token
  );

const tokenMatches = (expected: Redacted.Redacted, presented: string) =>
  timingSafeEqual(digest(Redacted.value(expected)), digest(presented));

const isMcpPath = (url: string) => {
  const [path = ""] = url.split("?");

  return path === MCP_PATH || path.startsWith(`${MCP_PATH}/`);
};

const unauthorized = HttpServerResponse.text(
  "A valid MCP bearer token is required.",
  {
    headers: { "www-authenticate": 'Bearer realm="zagrajmy-mcp"' },
    status: 401,
  }
);

export const gateMcp =
  (token: Option.Option<Redacted.Redacted>) =>
  <E, R>(app: Effect.Effect<HttpServerResponse.HttpServerResponse, E, R>) =>
    Effect.gen(function* gateMcpRequest() {
      const request = yield* HttpServerRequest.HttpServerRequest;

      if (!isMcpPath(request.url) || Option.isNone(token)) {
        return yield* app;
      }

      const presented = bearerOf(request.headers.authorization);

      if (
        Option.exists(presented, (value) => tokenMatches(token.value, value))
      ) {
        return yield* app;
      }

      return unauthorized;
    });
