import { Schema } from "effect";

import { FormError } from "./form-error.js";

export class FormInvalid extends Schema.TaggedError<FormInvalid>()(
  "FormInvalid",
  { errors: Schema.Array(FormError) },
  { description: "FormInvalid", httpApiStatus: 422 }
) {
  override get message(): string {
    return this.errors.map((error) => error.msgid).join(" ");
  }
}
