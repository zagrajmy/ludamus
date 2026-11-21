import { Context } from "effect";
import type { Effect } from "effect";

import type { Announcement } from "../announcement.js";
import type { SphereId } from "../sphere.js";
import type { StoreFailure } from "./store-error.js";

export class AnnouncementStore extends Context.Service<
  AnnouncementStore,
  {
    readonly listPublished: (
      sphereId: SphereId
    ) => Effect.Effect<readonly Announcement[], StoreFailure>;
  }
>()("@zagrajmy/core/AnnouncementStore") {}
