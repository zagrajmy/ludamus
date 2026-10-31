import { Effect, Schema } from "effect";
import { Command } from "foldkit";

import { encounterSharePath } from "../../ui/feed-card.js";
import { EventsFeedMessage } from "./message.js";

class ClipboardUnavailable extends Schema.TaggedError<ClipboardUnavailable>()(
  "ClipboardUnavailable",
  { reason: Schema.String }
) {
  override get message(): string {
    return "The clipboard refused the share link";
  }
}

export const CopyShareLink = Command.define("CopyShareLink", {
  args: { shareCode: Schema.String },
  execute: ({ shareCode }) =>
    Effect.tryPromise({
      catch: (cause) => new ClipboardUnavailable({ reason: String(cause) }),
      try: async () =>
        navigator.clipboard.writeText(
          `${window.location.origin}${encounterSharePath(shareCode)}`
        ),
    }).pipe(
      Effect.match({
        onFailure: () => EventsFeedMessage.FailedCopyShareLink({ shareCode }),
        onSuccess: () =>
          EventsFeedMessage.SucceededCopyShareLink({ shareCode }),
      })
    ),
  messages: [
    EventsFeedMessage.FailedCopyShareLink,
    EventsFeedMessage.SucceededCopyShareLink,
  ],
});

export const WaitBeforeCopyReset = Command.define("WaitBeforeCopyReset", {
  args: { shareCode: Schema.String },
  execute: ({ shareCode }) =>
    Effect.sleep("2 seconds").pipe(
      Effect.as(EventsFeedMessage.CompletedWaitBeforeCopyReset({ shareCode }))
    ),
  messages: [EventsFeedMessage.CompletedWaitBeforeCopyReset],
});
