import { Schema } from "effect";

import { FormErrors } from "../proposal/form-fields.js";
import { ProposeStep } from "../proposal/wizard.js";

export class ProposalInvalid extends Schema.TaggedError<ProposalInvalid>()(
  "ProposalInvalid",
  { errors: FormErrors, step: ProposeStep },
  { httpApiStatus: 422 }
) {
  override get message(): string {
    return `The ${this.step} step has errors: ${Object.keys(this.errors).join(", ")}`;
  }
}
