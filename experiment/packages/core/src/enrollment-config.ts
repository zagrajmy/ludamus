import { Schema } from "effect";

import { EnrollmentConfigId, EventId } from "./ids.js";

export const EnrollmentWindow = Schema.Struct({
  allowAnonymousEnrollment: Schema.Boolean,
  bannerText: Schema.String,
  endTime: Schema.DateTimeUtc,
  limitToEndTime: Schema.Boolean,
  maxWaitlistSessions: Schema.Int,
  percentageSlots: Schema.Int,
  restrictToConfiguredUsers: Schema.Boolean,
  startTime: Schema.DateTimeUtc,
});

export type EnrollmentWindow = typeof EnrollmentWindow.Type;

export const EnrollmentConfig = Schema.Struct({
  ...EnrollmentWindow.fields,
  eventId: EventId,
  id: EnrollmentConfigId,
});

export type EnrollmentConfig = typeof EnrollmentConfig.Type;

export const UserEnrollmentConfig = Schema.Struct({
  allowedSlots: Schema.Int,
  enrollmentConfigId: EnrollmentConfigId,
  fetchedFromApi: Schema.Boolean,
  id: Schema.Int,
  lastCheck: Schema.NullOr(Schema.DateTimeUtc),
  userEmail: Schema.String,
});

export type UserEnrollmentConfig = typeof UserEnrollmentConfig.Type;

export const NewUserEnrollmentConfig = Schema.Struct({
  allowedSlots: Schema.Int,
  enrollmentConfigId: EnrollmentConfigId,
  fetchedFromApi: Schema.Boolean,
  lastCheck: Schema.NullOr(Schema.DateTimeUtc),
  userEmail: Schema.String,
});

export type NewUserEnrollmentConfig = typeof NewUserEnrollmentConfig.Type;

export const DomainEnrollmentConfig = Schema.Struct({
  allowedSlotsPerUser: Schema.Int,
  domain: Schema.String,
  enrollmentConfigId: EnrollmentConfigId,
  id: Schema.Int,
});

export type DomainEnrollmentConfig = typeof DomainEnrollmentConfig.Type;

export const SlotAllowance = Schema.Struct({
  allowedSlots: Schema.Int,
  key: Schema.String,
});

export type SlotAllowance = typeof SlotAllowance.Type;
