import { Schema } from "effect";

export const Locale = Schema.Literals(["en", "pl"]);

export type Locale = typeof Locale.Type;

export const DEFAULT_LOCALE: Locale = "pl";
