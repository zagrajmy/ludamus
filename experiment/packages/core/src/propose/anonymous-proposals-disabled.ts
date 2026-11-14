import { Schema } from "effect";

export class AnonymousProposalsDisabled extends Schema.TaggedError<AnonymousProposalsDisabled>()(
  "AnonymousProposalsDisabled",
  { eventSlug: Schema.String },
  { httpApiStatus: 401 }
) {
  override get message(): string {
    return `${this.eventSlug} takes proposals from signed-in people only.`;
  }
}
