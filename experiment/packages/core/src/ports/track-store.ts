import { Context } from "effect";
import type { Effect, Option } from "effect";

import type { EventId, SpaceId, TrackId, UserId } from "../ids.js";
import type { Track, TrackListItem, TrackWrite } from "../track.js";
import type { DuplicateName, NotFound, StoreFailure } from "./store-error.js";

export class TrackStore extends Context.Service<
  TrackStore,
  {
    readonly listByEvent: (
      eventId: EventId
    ) => Effect.Effect<readonly Track[], StoreFailure>;
    readonly listPublicByEvent: (
      eventId: EventId
    ) => Effect.Effect<readonly Track[], StoreFailure>;
    readonly listWithAssignments: (
      eventId: EventId
    ) => Effect.Effect<readonly TrackListItem[], StoreFailure>;
    readonly listByManager: (options: {
      readonly userId: UserId;
      readonly eventId: EventId | null;
    }) => Effect.Effect<readonly Track[], StoreFailure>;
    readonly readBySlug: (options: {
      readonly eventId: EventId;
      readonly slug: string;
    }) => Effect.Effect<Track, NotFound | StoreFailure>;
    readonly readInEvent: (options: {
      readonly eventId: EventId;
      readonly id: TrackId;
    }) => Effect.Effect<Track, NotFound | StoreFailure>;
    readonly findByName: (options: {
      readonly eventId: EventId;
      readonly name: string;
    }) => Effect.Effect<Option.Option<Track>, StoreFailure>;
    readonly slugExists: (options: {
      readonly eventId: EventId;
      readonly slug: string;
      readonly excludeId: TrackId | null;
    }) => Effect.Effect<boolean, StoreFailure>;
    readonly spaceIds: (
      trackId: TrackId
    ) => Effect.Effect<readonly SpaceId[], StoreFailure>;
    readonly managerIds: (
      trackId: TrackId
    ) => Effect.Effect<readonly UserId[], StoreFailure>;
    readonly create: (options: {
      readonly eventId: EventId;
      readonly track: TrackWrite;
    }) => Effect.Effect<Track, DuplicateName | StoreFailure>;
    readonly update: (options: {
      readonly eventId: EventId;
      readonly id: TrackId;
      readonly track: TrackWrite;
    }) => Effect.Effect<Track, DuplicateName | NotFound | StoreFailure>;
    readonly delete: (options: {
      readonly eventId: EventId;
      readonly id: TrackId;
    }) => Effect.Effect<void, NotFound | StoreFailure>;
  }
>()("@zagrajmy/core/TrackStore") {}
