import { Context } from "effect";
import type { Effect } from "effect";

import type { EventId, UserId } from "../ids.js";
import type { ReusableSessionRecord } from "../propose/schemas.js";
import type { SphereId } from "../sphere.js";
import type { StoreFailure } from "./store-error.js";

export class ProposerStore extends Context.Service<
  ProposerStore,
  {
    readonly listReusableSessions: (options: {
      readonly userId: UserId;
      readonly sphereId: SphereId;
      readonly excludeEventId: EventId;
      readonly limit: number;
    }) => Effect.Effect<readonly ReusableSessionRecord[], StoreFailure>;
    readonly fillDiscordUsername: (options: {
      readonly userId: UserId;
      readonly handle: string;
    }) => Effect.Effect<boolean, StoreFailure>;
  }
>()("@zagrajmy/core/ProposerStore") {}
