import { Result, Schema } from "effect";

import catalogFile from "./catalog.generated.json" with { type: "json" };
import { compilePluralForms } from "./plural-rule.js";

const CONTEXT_SEPARATOR = "\u0004";

const CatalogFile = Schema.Struct({
  language: Schema.Literal("pl"),
  messages: Schema.Record(Schema.String, Schema.String),
  pluralForms: Schema.String,
  plurals: Schema.Record(Schema.String, Schema.Array(Schema.String)),
});

const polish = Schema.decodeUnknownSync(CatalogFile)(catalogFile);

const polishPlurals = Result.getOrThrow(compilePluralForms(polish.pluralForms));

export const catalogKey = (context: string | undefined, msgid: string) =>
  context === undefined ? msgid : `${context}${CONTEXT_SEPARATOR}${msgid}`;

export const polishMessage = (key: string) =>
  Object.hasOwn(polish.messages, key) ? polish.messages[key] : undefined;

export const polishPluralForm = (key: string, count: number) =>
  Object.hasOwn(polish.plurals, key)
    ? polish.plurals[key]?.[polishPlurals.select(count)]
    : undefined;
