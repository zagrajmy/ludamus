import { Schema } from "effect";

export const FormErrorVars = Schema.Record(
  Schema.String,
  Schema.Union([Schema.String, Schema.Number])
);

export const FormError = Schema.Struct({
  field: Schema.String,
  msgid: Schema.String,
  vars: FormErrorVars,
});

export type FormError = typeof FormError.Type;

export const formError = (
  field: string,
  msgid: string,
  vars: typeof FormErrorVars.Type = {}
): FormError => ({ field, msgid, vars });
