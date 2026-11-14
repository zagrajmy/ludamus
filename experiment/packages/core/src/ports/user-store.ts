import { Context } from "effect";
import type { Effect } from "effect";

import type { UserId } from "../ids.js";
import type { Sponsorship, User, UserSummary } from "../user.js";
import type { NotFound, StoreFailure } from "./store-error.js";

export class UserDirectory extends Context.Service<
  UserDirectory,
  {
    readonly readBySlug: (
      slug: string
    ) => Effect.Effect<User, NotFound | StoreFailure>;
    readonly readById: (
      id: UserId
    ) => Effect.Effect<User, NotFound | StoreFailure>;
    readonly listByIds: (
      ids: readonly UserId[]
    ) => Effect.Effect<readonly UserSummary[], StoreFailure>;
    readonly companionsOf: (
      managerId: UserId
    ) => Effect.Effect<readonly UserSummary[], StoreFailure>;
    readonly sponsorsOf: (
      memberIds: readonly UserId[]
    ) => Effect.Effect<readonly Sponsorship[], StoreFailure>;
  }
>()("@zagrajmy/core/UserDirectory") {}
