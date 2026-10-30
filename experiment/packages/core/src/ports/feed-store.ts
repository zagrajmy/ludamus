import { Context } from "effect";
import type { Effect } from "effect";

import type {
  AnnouncementRow,
  FeedEncounterRow,
  FeedEventRow,
} from "../feed.js";
import type { StoreError } from "./event-store.js";

export type EncounterWindow = Readonly<{
  now: string;
  sphereId: number;
  viewerId: number | null;
}>;

export class FeedStore extends Context.Service<
  FeedStore,
  {
    readonly listAnnouncements: (
      sphereId: number
    ) => Effect.Effect<readonly AnnouncementRow[], StoreError>;
    readonly listEvents: (
      sphereId: number
    ) => Effect.Effect<readonly FeedEventRow[], StoreError>;
    readonly listPastEncounters: (
      window: EncounterWindow
    ) => Effect.Effect<readonly FeedEncounterRow[], StoreError>;
    readonly listUpcomingEncounters: (
      window: EncounterWindow
    ) => Effect.Effect<readonly FeedEncounterRow[], StoreError>;
  }
>()("@zagrajmy/core/FeedStore") {}
