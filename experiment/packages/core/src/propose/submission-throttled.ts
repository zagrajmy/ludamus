import { Schema } from "effect";

export class SubmissionThrottled extends Schema.TaggedError<SubmissionThrottled>()(
  "SubmissionThrottled",
  { eventSlug: Schema.String },
  { httpApiStatus: 429 }
) {
  override get message(): string {
    return `Too many proposals to ${this.eventSlug} from this address; wait before submitting another.`;
  }
}
