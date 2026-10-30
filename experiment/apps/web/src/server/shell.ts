import type { ViewerChromeRow } from "@zagrajmy/core/feed";
import { Config, Effect, Option } from "effect";

import type { ShellFlags, ShellViewer } from "../client/shell/flags.js";
import {
  absoluteUrl,
  mediaUrl,
  rootOrigin,
  sphereOrigin,
} from "./request-context.js";
import type { RequestContext } from "./request-context.js";

const hex = (bytes: ArrayBuffer) =>
  [...new Uint8Array(bytes)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");

const gravatarUrl = Effect.fn("Shell.gravatarUrl")(function* gravatarUrl(
  email: string
) {
  const normalized = email.trim().toLowerCase();

  if (normalized === "") {
    return Option.none<string>();
  }

  const digest = yield* Effect.promise(() =>
    crypto.subtle.digest("SHA-256", new TextEncoder().encode(normalized))
  );

  return Option.some(
    `https://www.gravatar.com/avatar/${hex(digest)}?s=64&d=blank`
  );
});

const shellViewer = Effect.fn("Shell.viewer")(function* shellViewer(
  viewer: ViewerChromeRow,
  hasPanelAccess: boolean
) {
  const avatarUrl =
    viewer.useGravatar === 1 || viewer.avatarUrl === ""
      ? yield* gravatarUrl(viewer.email)
      : Option.some(viewer.avatarUrl);
  const found: ShellViewer = {
    avatarUrl,
    email: viewer.email,
    hasPanelAccess,
    name: viewer.name === "" ? viewer.username : viewer.name,
  };

  return found;
});

export const loadShellFlags = Effect.fn("Shell.load")(function* loadShellFlags(
  context: RequestContext
) {
  const supportEmail = yield* Config.String("SUPPORT_EMAIL").pipe(
    Config.withDefault("support@example.com")
  );
  const viewer = Option.isNone(context.viewer)
    ? Option.none<ShellViewer>()
    : Option.some(
        yield* shellViewer(context.viewer.value, context.hasPanelAccess)
      );
  const root = rootOrigin(context);
  const flags: ShellFlags = {
    analyticsEnabled: false,
    flashes: [],
    isRootSphere: context.isRootSphere,
    links: {
      about: `${root}/about/`,
      board: Option.none(),
      brand: "/brand/",
      dashboard: `${root}/dashboard/`,
      home: `${root}/`,
      login: `/crowd/auth0/do/login?next=${encodeURIComponent(absoluteUrl(context))}`,
      logout: "/crowd/auth0/do/logout",
      panel: context.hasPanelAccess ? Option.some("/panel/") : Option.none(),
      profile: "/crowd/profile/",
      sphere: `${sphereOrigin(context)}/`,
    },
    locale: context.translator.locale,
    requestUrl: absoluteUrl(context),
    sphere: {
      domain: context.sphere.domain,
      logoUrl:
        context.sphere.logo === ""
          ? Option.none()
          : Option.some(mediaUrl(context.sphere.logo)),
      name: context.sphere.name,
    },
    supportEmail,
    viewer,
    year: new Date(context.now.epochMillis).getUTCFullYear(),
  };

  return flags;
});
