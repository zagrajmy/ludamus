import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";

export const EnrollPageMessage = defineMessageUnion({
  ChangedGuests: { value: Schema.String },
  LeftEnrollPage: {},
  SubmittedEnrollments: {},
  ToggledPerson: { userId: Schema.Int },
});

export type EnrollPageMessage = typeof EnrollPageMessage.Type;
