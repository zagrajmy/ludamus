import { Context } from "effect";
import type { Effect, Option } from "effect";

import type {
  DomainEnrollmentConfig,
  EnrollmentConfig,
  NewUserEnrollmentConfig,
  SlotAllowance,
  UserEnrollmentConfig,
} from "../enrollment-config.js";
import type { EnrollmentConfigId, EventId } from "../ids.js";
import type { StoreFailure } from "./store-error.js";

export class EnrollmentConfigStore extends Context.Service<
  EnrollmentConfigStore,
  {
    readonly listByEvent: (
      eventId: EventId
    ) => Effect.Effect<readonly EnrollmentConfig[], StoreFailure>;
    readonly readUserConfig: (options: {
      readonly enrollmentConfigId: EnrollmentConfigId;
      readonly userEmail: string;
    }) => Effect.Effect<Option.Option<UserEnrollmentConfig>, StoreFailure>;
    readonly readDomainConfig: (options: {
      readonly enrollmentConfigId: EnrollmentConfigId;
      readonly domain: string;
    }) => Effect.Effect<Option.Option<DomainEnrollmentConfig>, StoreFailure>;
    readonly createUserConfig: (
      config: NewUserEnrollmentConfig
    ) => Effect.Effect<UserEnrollmentConfig, StoreFailure>;
    readonly updateUserConfig: (
      config: UserEnrollmentConfig
    ) => Effect.Effect<void, StoreFailure>;
    readonly userAllowances: (options: {
      readonly enrollmentConfigIds: readonly EnrollmentConfigId[];
      readonly emails: readonly string[];
    }) => Effect.Effect<readonly SlotAllowance[], StoreFailure>;
    readonly domainAllowances: (options: {
      readonly enrollmentConfigIds: readonly EnrollmentConfigId[];
      readonly domains: readonly string[];
    }) => Effect.Effect<readonly SlotAllowance[], StoreFailure>;
  }
>()("@zagrajmy/core/EnrollmentConfigStore") {}
