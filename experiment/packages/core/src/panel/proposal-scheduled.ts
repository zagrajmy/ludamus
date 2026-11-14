import { Schema } from "effect";

export class ProposalScheduled extends Schema.TaggedError<ProposalScheduled>()(
  "ProposalScheduled",
  {},
  { description: "ProposalScheduled", httpApiStatus: 409 }
) {
  override get message(): string {
    return `${this._tag}: this session is scheduled and can only be accepted.`;
  }
}
