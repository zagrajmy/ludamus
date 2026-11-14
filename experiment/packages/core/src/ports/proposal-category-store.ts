import { Context } from "effect";
import type { Effect } from "effect";

import type { EventId, ProposalCategoryId } from "../ids.js";
import type {
  CategoryRequirements,
  CategoryStats,
  ProposalCategory,
} from "../proposal-category.js";
import type { NotFound, StoreFailure } from "./store-error.js";

export class ProposalCategoryStore extends Context.Service<
  ProposalCategoryStore,
  {
    readonly listByEvent: (
      eventId: EventId
    ) => Effect.Effect<readonly ProposalCategory[], StoreFailure>;
    readonly readInEvent: (options: {
      readonly eventId: EventId;
      readonly id: ProposalCategoryId;
    }) => Effect.Effect<ProposalCategory, NotFound | StoreFailure>;
    readonly readBySlug: (options: {
      readonly eventId: EventId;
      readonly slug: string;
    }) => Effect.Effect<ProposalCategory, NotFound | StoreFailure>;
    readonly readRequirements: (
      categoryId: ProposalCategoryId
    ) => Effect.Effect<CategoryRequirements, StoreFailure>;
    readonly stats: (
      eventId: EventId
    ) => Effect.Effect<readonly CategoryStats[], StoreFailure>;
  }
>()("@zagrajmy/core/ProposalCategoryStore") {}
