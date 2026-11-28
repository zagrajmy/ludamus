import type { OfferResolution } from "@zagrajmy/core/contracts";
import { Effect, Schema } from "effect";
import { Command } from "foldkit";

import type { FlashLevel } from "../../ui/flash.js";
import { Locale, translator } from "../../ui/i18n.js";
import { navigateWithFlash } from "../panel/navigate.js";
import { Backend } from "../rpc.js";
import { OfferPageMessage } from "./message.js";

const OUTCOME_TEXT: Readonly<
  Record<
    OfferResolution["outcome"],
    { level: FlashLevel; claim: string; decline: string }
  >
> = {
  claimed: {
    claim: "Spot claimed — you are now confirmed for this session.",
    decline: "Spot claimed — you are now confirmed for this session.",
    level: "success",
  },
  conflict: {
    claim:
      "You hold a seat in a session that overlaps this one; leave it first.",
    decline:
      "You hold a seat in a session that overlaps this one; leave it first.",
    level: "error",
  },
  declined: {
    claim: "Offer declined — the seat was released.",
    decline: "Offer declined — the seat was released.",
    level: "success",
  },
  expired: {
    claim: "This offer has expired or was already claimed.",
    decline: "This offer is no longer available or has expired.",
    level: "error",
  },
  not_found: {
    claim: "This offer has expired or was already claimed.",
    decline: "This offer is no longer available or has expired.",
    level: "error",
  },
};

const settle = (options: {
  readonly resolution: OfferResolution;
  readonly action: "claim" | "decline";
  readonly locale: Locale;
}) => {
  const { resolution } = options;
  const copy = OUTCOME_TEXT[resolution.outcome];

  const landed =
    resolution.outcome === "claimed" || resolution.outcome === "declined";

  return navigateWithFlash(
    landed && resolution.eventSlug !== null
      ? `/event/${resolution.eventSlug}/`
      : "/",
    [
      {
        level: copy.level,
        text: translator(options.locale).t(copy[options.action]),
      },
    ]
  );
};

export const ResolveOffer = Command.define("ResolveOffer", {
  args: {
    action: Schema.Literals(["claim", "decline"]),
    locale: Locale,
    token: Schema.String,
  },
  execute: ({ action, locale, token }) =>
    Effect.gen(function* resolveOffer() {
      if (
        action === "decline" &&
        // oxlint-disable-next-line eslint/no-alert -- Django's hx-confirm and data-confirm use the native dialog, and the specs answer it through page.once("dialog").
        !window.confirm(
          translator(locale).t(
            "Decline this offer? The held seat will be released."
          )
        )
      ) {
        return OfferPageMessage.StayedOnOfferPage();
      }

      const backend = yield* Backend;

      const resolve =
        action === "claim" ? backend.claimOffer : backend.declineOffer;

      yield* resolve({ token }).pipe(
        Effect.flatMap((resolution) => settle({ action, locale, resolution })),
        Effect.catch(() =>
          settle({
            action,
            locale,
            resolution: {
              eventSlug: null,
              outcome: "not_found",
              sessionId: null,
            },
          })
        )
      );

      return OfferPageMessage.LeftOfferPage();
    }).pipe(Effect.provide(Backend.layer)),
  messages: [
    OfferPageMessage.LeftOfferPage,
    OfferPageMessage.StayedOnOfferPage,
  ],
});
