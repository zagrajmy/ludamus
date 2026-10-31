import { Context } from "effect";
import type { Effect } from "effect";

import type {
  PersonalDataAnswer,
  PersonalDataField,
  PersonalDataValueWrite,
  SessionField,
} from "../fields.js";
import type { EventId, FacilitatorId } from "../ids.js";
import type { NotFound, StoreFailure } from "./store-error.js";

export class FieldStore extends Context.Service<
  FieldStore,
  {
    readonly listSessionFields: (
      eventId: EventId
    ) => Effect.Effect<readonly SessionField[], StoreFailure>;
    readonly readSessionFieldBySlug: (options: {
      readonly eventId: EventId;
      readonly slug: string;
    }) => Effect.Effect<SessionField, NotFound | StoreFailure>;
    readonly listPersonalDataFields: (
      eventId: EventId
    ) => Effect.Effect<readonly PersonalDataField[], StoreFailure>;
    readonly readPersonalDataFieldBySlug: (options: {
      readonly eventId: EventId;
      readonly slug: string;
    }) => Effect.Effect<PersonalDataField, NotFound | StoreFailure>;
    readonly readPersonalData: (options: {
      readonly eventId: EventId;
      readonly facilitatorId: FacilitatorId;
    }) => Effect.Effect<readonly PersonalDataAnswer[], StoreFailure>;
    readonly savePersonalData: (options: {
      readonly eventId: EventId;
      readonly facilitatorId: FacilitatorId;
      readonly values: readonly PersonalDataValueWrite[];
    }) => Effect.Effect<void, StoreFailure>;
  }
>()("@zagrajmy/core/FieldStore") {}
