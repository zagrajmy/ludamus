import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";
import { UrlRequest } from "foldkit/navigation";
import { Url } from "foldkit/url";

export const Message = defineMessageUnion({
  ChangedUrl: { url: Url },
  ClickedLink: { request: UrlRequest },
  ToggledMenu: {},
  NavigatedAway: { href: Schema.String },
});
export type Message = typeof Message.Type;
