import { Stream } from "effect";
import { Subscription } from "foldkit";

import { Message } from "./message.js";
import type { Model } from "./model.js";
import { colorSchemeChanges } from "./shell/subscriptions.js";

export const subscriptions = Subscription.make<Model, Message>()(() => ({
  colorScheme: Subscription.persistentEntry(
    colorSchemeChanges.pipe(
      Stream.map((message) => Message.GotShellMessage({ message }))
    )
  ),
}));
