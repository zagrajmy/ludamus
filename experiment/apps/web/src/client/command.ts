import { Schema } from "effect";
import { Effect } from "effect";
import { Command } from "foldkit";
import { load } from "foldkit/navigation";

import { Message } from "./message.js";

export const LoadPage = Command.define("LoadPage", {
  args: { href: Schema.String },
  execute: ({ href }) =>
    load(href).pipe(Effect.as(Message.NavigatedAway({ href }))),
  messages: [Message.NavigatedAway],
});
