import { Context } from "effect";
import type { Effect, Option } from "effect";

import type {
  NavbarNotification,
  NavbarNotifications,
} from "../notification.js";
import type { StoreFailure } from "./store-error.js";

export class NotificationStore extends Context.Service<
  NotificationStore,
  {
    readonly navbar: (
      userId: number
    ) => Effect.Effect<NavbarNotifications, StoreFailure>;
    readonly readForRecipient: (options: {
      readonly userId: number;
      readonly id: number;
    }) => Effect.Effect<Option.Option<NavbarNotification>, StoreFailure>;
  }
>()("@zagrajmy/core/NotificationStore") {}
