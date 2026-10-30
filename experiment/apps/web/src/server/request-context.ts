import { SessionResolver } from "@zagrajmy/auth";
import type { SphereChromeRow, ViewerChromeRow } from "@zagrajmy/core/feed";
import { ShellStore } from "@zagrajmy/core/ports/shell-store";
import { Clock, Config, Effect, Option, Schema } from "effect";

import { negotiateLocale, translator } from "../ui/i18n.js";
import type { Translator } from "../ui/i18n.js";
import { instantFromMillis } from "./format/instant.js";
import type { Instant } from "./format/instant.js";

export class UnknownSphere extends Schema.TaggedError<UnknownSphere>()(
  "UnknownSphere",
  {
    host: Schema.String,
  }
) {
  override get message(): string {
    return `No sphere is served at ${this.host}`;
  }
}

export class MissingRootSphere extends Schema.TaggedError<MissingRootSphere>()(
  "MissingRootSphere",
  {
    siteId: Schema.Int,
  }
) {
  override get message(): string {
    return `No sphere belongs to the root site ${this.siteId}`;
  }
}

export type RequestContext = Readonly<{
  hasPanelAccess: boolean;
  host: string;
  isRootSphere: boolean;
  now: Instant;
  request: Request;
  rootSphere: SphereChromeRow;
  scheme: string;
  sphere: SphereChromeRow;
  translator: Translator;
  url: URL;
  viewer: Option.Option<ViewerChromeRow>;
}>;

const cookie = (header: string | null, name: string) =>
  (header ?? "")
    .split(";")
    .map((pair) => pair.trim())
    .find((pair) => pair.startsWith(`${name}=`))
    ?.slice(name.length + 1);

export const loadRequestContext = Effect.fn("RequestContext.load")(
  function* loadRequestContext(request: Request) {
    const url = new URL(request.url);
    const host = request.headers.get("host") ?? url.host;
    const shells = yield* ShellStore;
    const rootSiteId = yield* Config.Int("SITE_ID").pipe(Config.withDefault(1));
    const sphere = yield* shells.sphereByDomain(host);

    if (Option.isNone(sphere)) {
      return yield* new UnknownSphere({ host });
    }

    const rootSphere = yield* shells.sphereBySite(rootSiteId);

    if (Option.isNone(rootSphere)) {
      return yield* new MissingRootSphere({ siteId: rootSiteId });
    }

    const sessions = yield* SessionResolver;
    const user = yield* sessions.fromCookieHeader(
      request.headers.get("cookie")
    );
    const viewer = Option.isNone(user)
      ? Option.none<ViewerChromeRow>()
      : yield* shells.viewer({
          sphereId: sphere.value.id,
          userId: user.value.id,
        });
    const millis = yield* Clock.currentTimeMillis;
    const chosen = cookie(request.headers.get("cookie"), "django_language");
    const locale =
      chosen === "en" || chosen === "pl"
        ? chosen
        : negotiateLocale(request.headers.get("accept-language"));

    const context: RequestContext = {
      hasPanelAccess: Option.match(viewer, {
        onNone: () => false,
        onSome: (found) => found.isSuperuser === 1 || found.sphereRole !== null,
      }),
      host,
      isRootSphere: sphere.value.id === rootSphere.value.id,
      now: instantFromMillis(millis),
      request,
      rootSphere: rootSphere.value,
      scheme: url.protocol,
      sphere: sphere.value,
      translator: translator(locale),
      url,
      viewer,
    };

    return context;
  }
);

export const rootOrigin = (context: RequestContext) =>
  `${context.scheme}//${context.rootSphere.domain}`;

export const sphereOrigin = (context: RequestContext) =>
  `${context.scheme}//${context.sphere.domain}`;

export const absoluteUrl = (context: RequestContext) =>
  `${sphereOrigin(context)}${context.url.pathname}${context.url.search}`;

export const mediaUrl = (stored: string) => `/media/${stored}`;

export const placeholderCoverUrl = (key: number) =>
  `/static/placeholder-images/${String((key % 10) + 1).padStart(2, "0")}.webp`;
