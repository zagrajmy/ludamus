import { CurrentUser, SessionResolver } from "@zagrajmy/auth";
import { UnknownHost } from "@zagrajmy/capability/refusal";
import { CurrentSphere } from "@zagrajmy/core";
import { SphereStore } from "@zagrajmy/database";
import { CurrentLocale, negotiateLocale } from "@zagrajmy/i18n";
import { Context, Effect, Layer, Option } from "effect";
import type { Headers } from "effect/http/Headers";

export type RequestServices = CurrentLocale | CurrentSphere | CurrentUser;

const originHost = (origin: string) =>
  URL.canParse(origin) ? Option.some(new URL(origin).host) : Option.none();

export const isSameOrigin = (headers: Headers) => {
  if (headers["sec-fetch-site"] === "cross-site") {
    return false;
  }

  const { origin } = headers;

  if (origin === undefined) {
    return true;
  }

  return Option.exists(originHost(origin), (host) => host === headers.host);
};

const make = Effect.gen(function* makeRequestContext() {
  const spheres = yield* SphereStore;
  const sessions = yield* SessionResolver;

  const sphere = Effect.fn("RequestContext.sphere")(function* sphere(
    host: string | undefined
  ) {
    if (host === undefined || host === "") {
      return yield* new UnknownHost({ host: "" });
    }

    const found = yield* spheres.byDomain(host).pipe(Effect.orDie);

    if (Option.isNone(found)) {
      return yield* new UnknownHost({ host });
    }

    return found.value;
  });

  const user = Effect.fn("RequestContext.user")(function* user(
    headers: Headers
  ) {
    return yield* sessions.fromCookieHeader(headers.cookie ?? null);
  });

  const services = Effect.fn("RequestContext.services")(function* services(
    headers: Headers
  ) {
    const current = yield* sphere(headers.host);
    const viewer = yield* user(headers);

    return Context.make(CurrentSphere, current).pipe(
      Context.add(CurrentUser, viewer),
      Context.add(
        CurrentLocale,
        negotiateLocale(headers["accept-language"] ?? null)
      )
    );
  });

  return { services, sphere, user };
});

export class RequestContext extends Context.Service<
  RequestContext,
  Effect.Success<typeof make>
>()("@zagrajmy/server/RequestContext") {
  static readonly layer = Layer.effect(RequestContext, make);
}
