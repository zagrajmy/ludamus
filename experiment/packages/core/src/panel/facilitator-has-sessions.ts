import { Schema } from "effect";

export class FacilitatorHasSessions extends Schema.TaggedError<FacilitatorHasSessions>()(
  "FacilitatorHasSessions",
  { deleted: Schema.Int, live: Schema.Int },
  { description: "FacilitatorHasSessions", httpApiStatus: 409 }
) {
  override get message(): string {
    return `This facilitator is named on ${this.live + this.deleted} sessions`;
  }
}
