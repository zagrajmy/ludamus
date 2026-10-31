import { defineMessageUnion } from "foldkit/message";

export const OfferPageMessage = defineMessageUnion({
  ClickedClaim: {},
  ClickedDecline: {},
  LeftOfferPage: {},
  StayedOnOfferPage: {},
});

export type OfferPageMessage = typeof OfferPageMessage.Type;
