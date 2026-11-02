import { Context } from "effect";
import type { Effect, Option } from "effect";
import type { EnrollmentStoreError } from "../errors.js";
import type { EnrollmentWindow, EnrollmentWindowData } from "../schemas.js";

export class EnrollmentWindowStore extends Context.Service<
  EnrollmentWindowStore,
  {
    readonly listForEvent: (
      eventId: number
    ) => Effect.Effect<readonly EnrollmentWindow[], EnrollmentStoreError>;
    readonly read: (key: {
      readonly eventId: number;
      readonly pk: number;
    }) => Effect.Effect<Option.Option<EnrollmentWindow>, EnrollmentStoreError>;
    readonly create: (window: {
      readonly eventId: number;
      readonly data: EnrollmentWindowData;
    }) => Effect.Effect<EnrollmentWindow, EnrollmentStoreError>;
    readonly update: (window: {
      readonly eventId: number;
      readonly pk: number;
      readonly data: EnrollmentWindowData;
    }) => Effect.Effect<Option.Option<EnrollmentWindow>, EnrollmentStoreError>;
    readonly delete: (key: {
      readonly eventId: number;
      readonly pk: number;
    }) => Effect.Effect<boolean, EnrollmentStoreError>;
  }
>()("@zagrajmy/core/enrollment/EnrollmentWindowStore") {}
