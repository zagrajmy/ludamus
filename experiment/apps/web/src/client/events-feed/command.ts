import { Effect, Schema } from "effect";
import { Command } from "foldkit";

import { encounterSharePath } from "../../ui/feed-card.js";
import { EventsFeedMessage } from "./message.js";

export const CopyShareLink = Command.define("CopyShareLink", {
  args: { shareCode: Schema.String },
  execute: ({ shareCode }) =>
    Effect.tryPromise(async () => {
      await navigator.clipboard.writeText(
        `${window.location.origin}${encounterSharePath(shareCode)}`
      );
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
