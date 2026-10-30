import { Context } from "effect";
import type { Effect, Option } from "effect";

import type { SphereChromeRow, ViewerChromeRow } from "../feed.js";
import type { StoreError } from "./event-store.js";

export class ShellStore extends Context.Service<
  ShellStore,
  {
    readonly sphereByDomain: (
      domain: string
    ) => Effect.Effect<Option.Option<SphereChromeRow>, StoreError>;
    readonly sphereBySite: (
      siteId: number
    ) => Effect.Effect<Option.Option<SphereChromeRow>, StoreError>;
    readonly viewer: (options: {
      readonly sphereId: number;
      readonly userId: number;
    }) => Effect.Effect<Option.Option<ViewerChromeRow>, StoreError>;
  }
>()("@zagrajmy/core/ShellStore") {}
