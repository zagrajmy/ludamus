import { AppConfig } from "@zagrajmy/core";
import { DjangoSessionStore, UserStore } from "@zagrajmy/database";
import type { UserRow } from "@zagrajmy/database";
import { Context, DateTime, Effect, Layer, Option, Redacted } from "effect";

import { decodeSessionData, sessionAuthHash } from "./django-signing.js";

export class CurrentUser extends Context.Service<
  CurrentUser,
  Option.Option<UserRow>
>()("@zagrajmy/auth/CurrentUser") {}

export class SessionResolver extends Context.Service<
  SessionResolver,
  {
    readonly fromCookieHeader: (
      cookieHeader: string | null
    ) => Effect.Effect<Option.Option<UserRow>>;
  }
>()("@zagrajmy/auth/SessionResolver") {}

const SESSION_COOKIE = "sessionid";

export const cookieValue = (cookieHeader: string | null, name: string) => {
  if (cookieHeader === null) {
    return Option.none<string>();
  }

  for (const pair of cookieHeader.split(";")) {
    const separator = pair.indexOf("=");
    const key = (separator === -1 ? pair : pair.slice(0, separator)).trim();

    if (key === name) {
      return Option.some(pair.slice(separator + 1).trim());
    }
  }

  return Option.none<string>();
};

export const SessionResolverLive = Layer.effect(
  SessionResolver,
  Effect.gen(function* makeSessionResolver() {
    const secret = Redacted.value((yield* AppConfig).secretKey);
    const sessions = yield* DjangoSessionStore;
    const users = yield* UserStore;

    const resolve = Effect.fn("SessionResolver.resolve")(function* resolve(
      sessionKey: string
    ) {
      const row = yield* sessions.read(sessionKey);

      if (Option.isNone(row)) {
        return Option.none<UserRow>();
      }

      const expires = DateTime.make(
        `${row.value.expireDate.replace(" ", "T")}Z`
      );
      const now = yield* DateTime.now;

      if (Option.isSome(expires) && DateTime.isLessThan(expires.value, now)) {
        return Option.none<UserRow>();
      }

      const payload = yield* decodeSessionData(row.value.sessionData, secret);
      const userId = Number(payload._auth_user_id);

      if (!Number.isInteger(userId)) {
        return Option.none<UserRow>();
      }

      const user = yield* users.byId(userId);

      return Option.filter(
        user,
        (found) =>
          found.isActive === 1 &&
          payload._auth_user_hash === sessionAuthHash(found.password, secret)
      );
    });

    return SessionResolver.of({
      fromCookieHeader: (cookieHeader) =>
        cookieValue(cookieHeader, SESSION_COOKIE).pipe(
          Option.match({
            onNone: () => Effect.succeed(Option.none<UserRow>()),
            onSome: (key) =>
              resolve(key).pipe(
                Effect.catch((error) =>
                  Effect.logWarning("session rejected", error).pipe(
                    Effect.as(Option.none<UserRow>())
                  )
                )
              ),
          })
        ),
    });
  })
);
