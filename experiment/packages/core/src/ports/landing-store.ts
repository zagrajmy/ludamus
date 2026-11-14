import { Context } from "effect";
import type { Effect } from "effect";

import type { LandingConventionRow, LandingStatsRow } from "../feed.js";
import type { StoreError } from "./event-store.js";

export class LandingStore extends Context.Service<
  LandingStore,
  {
    readonly conventions: (options: {
      readonly domains: readonly string[];
      readonly now: string;
    }) => Effect.Effect<readonly LandingConventionRow[], StoreError>;
    readonly stats: Effect.Effect<LandingStatsRow, StoreError>;
  }
>()("@zagrajmy/core/LandingStore") {}
