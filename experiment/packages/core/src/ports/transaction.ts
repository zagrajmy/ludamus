import { Context } from "effect";
import type { Effect } from "effect";

import type { StoreError } from "./store-error.js";

export class StoreTransaction extends Context.Service<
  StoreTransaction,
  {
    readonly atomic: <A, E, R>(
      effect: Effect.Effect<A, E, R>
    ) => Effect.Effect<A, E | StoreError, R>;
  }
>()("@zagrajmy/core/StoreTransaction") {}
