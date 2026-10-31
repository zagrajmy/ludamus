import type { Update } from "foldkit";
import { modifyFields } from "foldkit/struct";

import { ReplaceAudienceHash } from "./command.js";
import { LandingMessage } from "./message.js";
import { audienceForHash } from "./model.js";
import type { LandingModel } from "./model.js";

type Return = Update.Return<LandingModel, LandingMessage>;

export const updateLanding = (
  model: LandingModel,
  message: LandingMessage
): Return =>
  LandingMessage.match<Return>(message, {
    ChangedAudience: ({ audience }) => ({
      commands: [ReplaceAudienceHash({ audience })],
      model: modifyFields(model, { audience: () => audience }),
    }),
    CompletedChoreography: () => ({
      model: modifyFields(model, { isChoreographyDone: () => true }),
    }),
    GotLocationHash: ({ hash }) =>
      hash === "" || audienceForHash(hash) === "players"
        ? {
            model: modifyFields(model, {
              audience: () => audienceForHash(hash),
            }),
          }
        : { model },
    ReplacedAudienceHash: () => ({ model }),
  });
