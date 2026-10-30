import { SessionResolver } from "@zagrajmy/auth";
import { CurrentSphere, EventStore, listEvents } from "@zagrajmy/core";
import { SphereStore } from "@zagrajmy/database";
import { Data, Effect, Option } from "effect";

import { Page } from "../client/model.js";
import type { Flags } from "../client/model.js";

export class UnknownSphere extends Data.TaggedError("UnknownSphere")<{
  readonly host: string;
}> {}

const pageFor = Effect.fn("loadFlags.page")(function* pageFor(pathname: string) {
  if (pathname === "/" || pathname === "/events/") {
    const events = yield* listEvents.handler({});

    return Page.EventsFeed({ events });
  }

  return Page.NotFound({ path: pathname });
});

export const loadFlags = Effect.fn("loadFlags")(function* loadFlags(
  request: Request
) {
  const host = request.headers.get("host") ?? new URL(request.url).host;
  const spheres = yield* SphereStore;
  const sphere = yield* spheres.byDomain(host);

  if (Option.isNone(sphere)) {
    return yield* new UnknownSphere({ host });
  }

  const sessions = yield* SessionResolver;
  const viewer = yield* sessions.fromCookieHeader(request.headers.get("cookie"));
  const locale = (request.headers.get("accept-language") ?? "").startsWith("pl")
    ? "pl"
    : "en";

  const page = yield* pageFor(new URL(request.url).pathname).pipe(
    Effect.provideService(CurrentSphere, sphere.value)
  );

  const flags: Flags = {
    page,
    shell: {
      locale,
      sphere: sphere.value,
      viewer: Option.map(viewer, (user) => ({
        displayName: user.name === "" ? user.username : user.name,
        id: user.id,
      })),
    },
  };

  return flags;
});

export type { EventStore };
