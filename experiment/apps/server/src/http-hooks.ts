import { CurrentUser } from "@zagrajmy/auth";
import type { AnyCapability, AnyContract } from "@zagrajmy/capability/contract";
import { UnknownHost } from "@zagrajmy/capability/refusal";
import { ClientIp, CurrentSphere, CurrentViewer } from "@zagrajmy/core";
import { CurrentLocale, negotiateLocale } from "@zagrajmy/i18n";
import { Effect, Option, Schema } from "effect";
import type { HttpServerRequest } from "effect/http";

import {
  Admission,
  admit,
  requirementOf,
  strictestRequirement,
} from "./access-policy.js";
import { isSameOrigin } from "./request-context.js";
import type { RequestContext } from "./request-context.js";

export const API_PREFIX = "/api";

interface Route {
  readonly contract: AnyContract;
  readonly method: string;
  readonly segments: readonly string[];
}

const segmentsOf = (path: string) =>
  path.split("/").filter((part) => part !== "");

const routeOf = (contract: AnyContract): Route => ({
  contract,
  method: contract.http?.method ?? "POST",
  segments: segmentsOf(
    `${API_PREFIX}${contract.http?.path ?? `/${contract.name}`}`
  ),
});

const matches = (route: Route, method: string, segments: readonly string[]) =>
  route.method === method &&
  route.segments.length === segments.length &&
  route.segments.every(
    (segment, index) => segment.startsWith(":") || segment === segments[index]
  );

export const contractForRequest = (
  all: readonly AnyCapability[],
  request: HttpServerRequest.HttpServerRequest
) => {
  const segments = segmentsOf(
    new URL(request.url, "http://request.invalid").pathname
  );

  return Option.fromNullishOr(
    all
      .map(({ contract }) => routeOf(contract))
      .find((route) => matches(route, request.method, segments))?.contract
  );
};

export const httpHooks = (
  context: RequestContext["Service"],
  all: readonly AnyCapability[]
) =>
  [
    {
      failure: UnknownHost,
      from: (request: HttpServerRequest.HttpServerRequest) =>
        context.sphere(request.headers.host),
      tag: CurrentSphere,
    },
    {
      failure: Admission,
      from: (request: HttpServerRequest.HttpServerRequest) =>
        Effect.gen(function* admitCaller() {
          const viewer = yield* context.user(request.headers);

          const requirement = Option.match(contractForRequest(all, request), {
            onNone: () =>
              strictestRequirement(`${request.method} ${request.url}`),
            onSome: requirementOf,
          });

          yield* admit(requirement, {
            sameOrigin: isSameOrigin(request.headers),
            signedIn: Option.isSome(viewer),
          });

          return viewer;
        }),
      tag: CurrentUser,
    },
    {
      failure: Schema.Never,
      from: (request: HttpServerRequest.HttpServerRequest) =>
        context.viewer(request.headers),
      tag: CurrentViewer,
    },
    {
      failure: Schema.Never,
      from: (request: HttpServerRequest.HttpServerRequest) =>
        Effect.succeed(
          negotiateLocale(request.headers["accept-language"] ?? null)
        ),
      tag: CurrentLocale,
    },
    {
      failure: Schema.Never,
      from: (request: HttpServerRequest.HttpServerRequest) =>
        Effect.succeed(context.clientIp(request.headers)),
      tag: ClientIp,
    },
  ] as const;
