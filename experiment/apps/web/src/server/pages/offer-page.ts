import { readOffer } from "@zagrajmy/core/enrollment/read-offer-capability";
import { formatDate } from "@zagrajmy/i18n";
import { DateTime, Effect } from "effect";

import type { OfferPageFlags } from "../../client/offer-page/flags.js";
import type { RequestContext } from "../request-context.js";
import { PageOutcome } from "./page-outcome.js";
import { providePanelServices } from "./panel/context.js";

export const OFFER_PAGE_PATH =
  /^\/offer\/(?<token>[^/]+)\/(?<action>claim|decline)\/$/u;

type OfferPageOutcome = PageOutcome<OfferPageFlags>;

export const loadOfferPage = Effect.fn("OfferPage.load")(
  function* loadOfferPage(context: RequestContext, token: string) {
    const gone: OfferPageOutcome = PageOutcome.Redirect({
      flashes: [
        {
          level: "error",
          text: context.translator.t(
            "This offer is no longer available or has expired."
          ),
        },
      ],
      location: "/",
    });

    return yield* readOffer.handler({ token }).pipe(
      providePanelServices(context),
      Effect.map((offer): OfferPageOutcome =>
        PageOutcome.Page({
          flags: {
            deadlineLabel: formatDate({
              format: "j E Y, G:i",
              locale: context.translator.locale,
              value: DateTime.formatIso(offer.offerExpiresAt),
            }),
            locale: context.translator.locale,
            offer,
            token,
          },
        })
      ),
      Effect.catchTag("NotFound", () => Effect.succeed(gone))
    );
  }
);
