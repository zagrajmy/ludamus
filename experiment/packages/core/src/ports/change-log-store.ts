import { Context } from "effect";
import type { Effect } from "effect";

import type {
  ChangeLogCursor,
  FacilitatorChangeLogEntry,
  NewFacilitatorChangeLog,
  NewScheduleChangeLog,
  ScheduleChangeLogEntry,
} from "../change-log.js";
import type { EventId, ScheduleChangeLogId, SessionId } from "../ids.js";
import type { StoreFailure } from "./store-error.js";

export interface ChangeLogPage<Key> {
  readonly key: Key;
  readonly before: ChangeLogCursor | null;
}

export class ChangeLogStore extends Context.Service<
  ChangeLogStore,
  {
    readonly logFacilitatorChange: (
      entry: NewFacilitatorChangeLog
    ) => Effect.Effect<void, StoreFailure>;
    readonly listFacilitatorChanges: (
      page: ChangeLogPage<EventId>
    ) => Effect.Effect<readonly FacilitatorChangeLogEntry[], StoreFailure>;
    readonly logScheduleChange: (
      entry: NewScheduleChangeLog
    ) => Effect.Effect<ScheduleChangeLogId, StoreFailure>;
    readonly listScheduleChanges: (
      page: ChangeLogPage<EventId>
    ) => Effect.Effect<readonly ScheduleChangeLogEntry[], StoreFailure>;
    readonly listScheduleChangesBySession: (
      page: ChangeLogPage<SessionId>
    ) => Effect.Effect<readonly ScheduleChangeLogEntry[], StoreFailure>;
  }
>()("@zagrajmy/core/ChangeLogStore") {}
