import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";
import { UrlRequest } from "foldkit/navigation";
import { Url } from "foldkit/url";

import { EnrollPageMessage } from "./enroll-page/message.js";
import { EventPageMessage } from "./event-page/message.js";
import { EventsFeedMessage } from "./events-feed/message.js";
import { LandingMessage } from "./landing/message.js";
import { OfferPageMessage } from "./offer-page/message.js";
import { PanelMessage } from "./panel/message.js";
import { ProposeMessage } from "./propose/message.js";
import { ShellMessage } from "./shell/message.js";

export const Message = defineMessageUnion({
  ChangedUrl: { url: Url },
  ClickedLink: { request: UrlRequest },
  GotEnrollPageMessage: { message: EnrollPageMessage },
  GotEventPageMessage: { message: EventPageMessage },
  GotEventsFeedMessage: { message: EventsFeedMessage },
  GotLandingMessage: { message: LandingMessage },
  GotOfferPageMessage: { message: OfferPageMessage },
  GotPanelMessage: { message: PanelMessage },
  GotProposeMessage: { message: ProposeMessage },
  GotShellMessage: { message: ShellMessage },
  LeftPage: { href: Schema.String },
});

export type Message = typeof Message.Type;
