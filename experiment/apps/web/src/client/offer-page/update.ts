import type { Update } from "foldkit";
import { modifyFields } from "foldkit/struct";

import { ResolveOffer } from "./command.js";
import { OfferPageMessage } from "./message.js";
import type { OfferPageModel } from "./model.js";

type Return = Update.Return<OfferPageModel, OfferPageMessage>;

const resolve = (model: OfferPageModel, action: "claim" | "decline"): Return =>
  model.busy
    ? { model }
    : {
        commands: [
          ResolveOffer({ action, locale: model.locale, token: model.token }),
        ],
        model: modifyFields(model, { busy: () => true }),
      };

export const updateOfferPage = (
  model: OfferPageModel,
  message: OfferPageMessage
): Return =>
  OfferPageMessage.match<Return>(message, {
    ClickedClaim: () => resolve(model, "claim"),
    ClickedDecline: () => resolve(model, "decline"),
    LeftOfferPage: () => ({ model }),
    StayedOnOfferPage: () => ({
      model: modifyFields(model, { busy: () => false }),
    }),
  });
