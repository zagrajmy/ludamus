import { defineContract } from "@zagrajmy/capability/contract";
import { Schema } from "effect";

import { EventSummary } from "./event.js";
import { StoreError } from "./ports/event-store.js";

export const listEventsContract = defineContract("listEvents", {
  annotations: { idempotent: true, readOnly: true },
  description: "Published events of the current sphere, soonest first",
  failure: StoreError,
  input: Schema.Struct({}),
  output: Schema.Array(EventSummary),
});
