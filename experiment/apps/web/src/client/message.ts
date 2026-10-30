import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";
import { UrlRequest } from "foldkit/navigation";
import { Url } from "foldkit/url";

import { EventsFeedMessage } from "./events-feed/message.js";
import { LandingMessage } from "./landing/message.js";
import { ShellMessage } from "./shell/message.js";

export const Message = defineMessageUnion({
  ChangedUrl: { url: Url },
  ClickedLink: { request: UrlRequest },
  GotEventsFeedMessage: { message: EventsFeedMessage },
  GotLandingMessage: { message: LandingMessage },
  GotShellMessage: { message: ShellMessage },
  LeftPage: { href: Schema.String },
});

export type Message = typeof Message.Type;
