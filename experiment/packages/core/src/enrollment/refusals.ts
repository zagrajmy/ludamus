import { Schema } from "effect";

import { EnrollFooter } from "./footer.js";

export const MessageLevel = Schema.Literals(["success", "warning", "error"]);

export type MessageLevel = typeof MessageLevel.Type;

export const MessageItem = Schema.Struct({
  msgid: Schema.String,
  name: Schema.String,
});

export type MessageItem = typeof MessageItem.Type;

export const EnrollmentNotice = Schema.Struct({
  args: Schema.Array(Schema.String),
  items: Schema.Array(MessageItem),
  level: MessageLevel,
  msgid: Schema.String,
  vars: Schema.Record(Schema.String, Schema.String),
});

export type EnrollmentNotice = typeof EnrollmentNotice.Type;

export const RefusalDestination = Schema.Literals([
  "enrollPage",
  "event",
  "index",
  "stay",
]);

export type RefusalDestination = typeof RefusalDestination.Type;

export class EnrollmentRefused extends Schema.TaggedError<EnrollmentRefused>()(
  "EnrollmentRefused",
  {
    destination: RefusalDestination,
    eventSlug: Schema.NullOr(Schema.String),
    footer: Schema.NullOr(EnrollFooter),
    notices: Schema.Array(EnrollmentNotice),
  },
  { httpApiStatus: 422 }
) {
  override get message(): string {
    return this.notices.map((notice) => notice.msgid).join(" ");
  }
}
