import { Option } from "effect";
import type { Update } from "foldkit";
import { modifyFields } from "foldkit/struct";

import { CopyShareLink, WaitBeforeCopyReset } from "./command.js";
import { EventsFeedMessage } from "./message.js";
import type { EventsFeedModel } from "./model.js";

type Return = Update.Return<EventsFeedModel, EventsFeedMessage>;

const isShowing = (model: EventsFeedModel, shareCode: string) =>
  Option.contains(model.copiedShareCode, shareCode);

export const updateEventsFeed = (
  model: EventsFeedModel,
  message: EventsFeedMessage
): Return =>
  EventsFeedMessage.match<Return>(message, {
    ClickedCopyShareLink: ({ shareCode }) => ({
      commands: [CopyShareLink({ shareCode })],
      model,
    }),
    CompletedWaitBeforeCopyReset: ({ shareCode }) => ({
      model: isShowing(model, shareCode)
        ? modifyFields(model, { copiedShareCode: () => Option.none() })
        : model,
    }),
    FailedCopyShareLink: () => ({ model }),
    SucceededCopyShareLink: ({ shareCode }) => ({
      commands: [WaitBeforeCopyReset({ shareCode })],
      model: modifyFields(model, {
        copiedShareCode: () => Option.some(shareCode),
      }),
    }),
  });
