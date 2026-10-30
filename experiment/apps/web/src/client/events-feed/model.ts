import { Option, Schema } from "effect";

import { EventsFeedFlags } from "./flags.js";

export const EventsFeedModel = Schema.Struct({
  ...EventsFeedFlags.fields,
  copiedShareCode: Schema.Option(Schema.String),
});
export type EventsFeedModel = typeof EventsFeedModel.Type;

export const initEventsFeed = (flags: EventsFeedFlags): EventsFeedModel => ({
  ...flags,
  copiedShareCode: Option.none(),
});
