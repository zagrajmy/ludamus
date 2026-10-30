import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";

export const EventsFeedMessage = defineMessageUnion({
  ClickedCopyShareLink: { shareCode: Schema.String },
  CompletedWaitBeforeCopyReset: { shareCode: Schema.String },
  FailedCopyShareLink: { shareCode: Schema.String },
  SucceededCopyShareLink: { shareCode: Schema.String },
});
export type EventsFeedMessage = typeof EventsFeedMessage.Type;
