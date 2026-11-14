import { implement } from "@zagrajmy/capability/implement";
import { Effect } from "effect";

import { listEventsContract } from "./contracts.js";
import { CurrentSphere } from "./ports/current-sphere.js";
import { EventStore } from "./ports/event-store.js";

export const listEvents = implement(listEventsContract, () =>
  Effect.gen(function* listEventsHandler() {
    const sphere = yield* CurrentSphere;
    const store = yield* EventStore;

    return yield* store.listPublished(sphere.id);
  })
);
