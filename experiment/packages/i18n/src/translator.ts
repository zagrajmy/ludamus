import { catalogKey, polishMessage, polishPluralForm } from "./catalog.js";
import type { Locale } from "./locale-schema.js";

export type MessageVars = Readonly<Record<string, string | number>>;

export interface Translator {
  readonly locale: Locale;
  readonly t: (msgid: string, vars?: MessageVars) => string;
  readonly tc: (context: string, msgid: string, vars?: MessageVars) => string;
  readonly n: (
    singular: string,
    plural: string,
    count: number,
    vars?: MessageVars
  ) => string;
  readonly nc: (
    context: string,
    singular: string,
    plural: string,
    count: number,
    vars?: MessageVars
  ) => string;
}

const asInteger = (value: string | number) => {
  const number = Number(value);

  return Number.isFinite(number) ? String(Math.trunc(number)) : String(value);
};

export const interpolate = (message: string, vars: MessageVars = {}) =>
  message.replaceAll(
    /\{\{\s*(\w+)\s*\}\}|\{(\w+)\}|%\((\w+)\)([sdi])|%%/g,
    (token, double, single, python, conversion) => {
      if (token === "%%") {
        return "%";
      }

      const name = String(double ?? single ?? python);

      if (!Object.hasOwn(vars, name)) {
        return token;
      }

      const value = vars[name] ?? "";

      return conversion === "d" || conversion === "i"
        ? asInteger(value)
        : String(value);
    }
  );

const englishPlural = (singular: string, plural: string, count: number) =>
  count === 1 ? singular : plural;

export const translator = (locale: Locale): Translator => {
  const lookup = (context: string | undefined, msgid: string) =>
    locale === "pl"
      ? (polishMessage(catalogKey(context, msgid)) ?? msgid)
      : msgid;

  const lookupPlural = (
    context: string | undefined,
    forms: { singular: string; plural: string; count: number }
  ) =>
    (locale === "pl"
      ? polishPluralForm(catalogKey(context, forms.singular), forms.count)
      : undefined) ?? englishPlural(forms.singular, forms.plural, forms.count);

  return {
    locale,
    n: (singular, plural, count, vars) =>
      interpolate(lookupPlural(undefined, { count, plural, singular }), vars),
    nc: (context, singular, plural, count, vars) =>
      interpolate(lookupPlural(context, { count, plural, singular }), vars),
    t: (msgid, vars) => interpolate(lookup(undefined, msgid), vars),
    tc: (context, msgid, vars) => interpolate(lookup(context, msgid), vars),
  };
};
