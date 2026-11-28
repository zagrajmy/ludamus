import { Schema } from "effect";

export class ProposalsClosed extends Schema.TaggedError<ProposalsClosed>()(
  "ProposalsClosed",
  { eventIsOpen: Schema.Boolean, eventSlug: Schema.String },
  { httpApiStatus: 409 }
) {
  override get message(): string {
    return `Proposal submission is not currently active for ${this.eventSlug}.`;
  }
}
