import { Context } from "effect";
import type { Effect } from "effect";

import type { Encounter } from "../encounter.js";
import type { SphereId } from "../sphere.js";
import type { StoreFailure } from "./store-error.js";

export class EncounterStore extends Context.Service<
  EncounterStore,
  {
    readonly listPublic: (
      sphereId: SphereId
    ) => Effect.Effect<readonly Encounter[], StoreFailure>;
  }
>()("@zagrajmy/core/EncounterStore") {}
