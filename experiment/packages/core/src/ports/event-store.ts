import { Context, Schema } from "effect";
import type { Effect } from "effect";

import type { EventSummary } from "../event.js";
import type { SphereId } from "../sphere.js";

export class StoreError extends Schema.TaggedError<
  StoreError,
  { readonly brand: unique symbol }
>()("StoreError", {
  operation: Schema.String,
  reason: Schema.String,
}) {
  override get message(): string {
    return `${this.operation} failed: ${this.reason}`;
  }
}

export class EventStore extends Context.Service<
  EventStore,
  {
    readonly listPublished: (
      sphereId: SphereId
    ) => Effect.Effect<ReadonlyArray<EventSummary>, StoreError>;
  }
>()("@zagrajmy/core/EventStore") {}
