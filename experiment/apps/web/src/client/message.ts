import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";
import { UrlRequest } from "foldkit/navigation";
import { Url } from "foldkit/url";

import * as ProposalAccept from "./accept/message.js";
import * as EnrollPage from "./enroll-page/message.js";
import * as EventPage from "./event-page/message.js";
import * as EventsFeed from "./events-feed/message.js";
import * as Landing from "./landing/message.js";
import * as OfferPage from "./offer-page/message.js";
import * as Panel from "./panel/message.js";
import * as Propose from "./propose/message.js";
import * as Shell from "./shell/message.js";

export const Message = defineMessageUnion({
  ChangedUrl: { url: Url },
  ClickedLink: { request: UrlRequest },
  GotEnrollPageMessage: { message: EnrollPage.Message },
  GotEventPageMessage: { message: EventPage.Message },
  GotEventsFeedMessage: { message: EventsFeed.Message },
  GotLandingMessage: { message: Landing.Message },
  GotOfferPageMessage: { message: OfferPage.Message },
  GotPanelMessage: { message: Panel.Message },
  GotProposalAcceptMessage: { message: ProposalAccept.Message },
  GotProposeMessage: { message: Propose.Message },
  GotShellMessage: { message: Shell.Message },
  LeftPage: { href: Schema.String },
});

export type Message = typeof Message.Type;
