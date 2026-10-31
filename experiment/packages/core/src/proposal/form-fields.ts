import { Option, Result, Schema } from "effect";

import { parseIpv4Address, parseIpv6Address } from "./client-ip.js";
import {
  PY_DECIMAL_CLASS,
  PY_SPACE_CLASS,
  pyDecimalInt,
  pyLength,
  pyStrip,
} from "./python-text.js";

export const FieldErrorVars = Schema.Record(
  Schema.String,
  Schema.Union([Schema.String, Schema.Number])
);

export const FieldError = Schema.Struct({
  code: Schema.String,
  msgid: Schema.String,
  plural: Schema.NullOr(
    Schema.Struct({ count: Schema.Int, msgid: Schema.String })
  ),
  vars: FieldErrorVars,
});

export type FieldError = typeof FieldError.Type;

export const FormErrors = Schema.Record(
  Schema.String,
  Schema.Array(FieldError)
);

export type FormErrors = typeof FormErrors.Type;

export const fieldError = (
  code: string,
  msgid: string,
  vars: Readonly<Record<string, string | number>> = {}
): FieldError => ({ code, msgid, plural: null, vars });

export const REQUIRED_ERROR = fieldError("required", "This field is required.");

export const NULL_CHARACTERS_ERROR = fieldError(
  "null_characters_not_allowed",
  "Null characters are not allowed."
);

export const maxLengthError = (options: {
  readonly limit: number;
  readonly length: number;
}): FieldError => ({
  code: "max_length",
  msgid:
    "Ensure this value has at most %(limit_value)d character (it has %(show_value)d).",
  plural: {
    count: options.limit,
    msgid:
      "Ensure this value has at most %(limit_value)d characters (it has %(show_value)d).",
  },
  vars: { limit_value: options.limit, show_value: options.length },
});

export const invalidChoiceError = (value: string): FieldError =>
  fieldError(
    "invalid_choice",
    "Select a valid choice. %(value)s is not one of the available choices.",
    { value }
  );

export const CUSTOM_ANSWER_REQUIRED_ERROR = fieldError(
  "custom_answer_required",
  "Pick an option or type your own."
);

const INVALID_INTEGER_ERROR = fieldError("invalid", "Enter a whole number.");

const INVALID_EMAIL_ERROR = fieldError(
  "invalid",
  "Enter a valid email address."
);

export const STORAGE_LIMIT_ERROR = fieldError(
  "max_value",
  "Enter a smaller number."
);

const minValueError = (limit: number): FieldError =>
  fieldError(
    "min_value",
    "Ensure this value is greater than or equal to %(limit_value)s.",
    { limit_value: limit }
  );

const maxValueError = (limit: number): FieldError =>
  fieldError(
    "max_value",
    "Ensure this value is less than or equal to %(limit_value)s.",
    { limit_value: limit }
  );

export type FormData = Readonly<Record<string, readonly string[]>>;

export const lastPosted = (data: FormData, key: string): string =>
  data[key]?.at(-1) ?? "";

export type Cleaned<A> = Result.Result<A, readonly FieldError[]>;

const charValidators = (
  value: string,
  maxLength: number | null
): readonly FieldError[] => [
  ...(maxLength !== null && pyLength(value) > maxLength
    ? [maxLengthError({ length: pyLength(value), limit: maxLength })]
    : []),
  ...(value.includes("\u0000") ? [NULL_CHARACTERS_ERROR] : []),
];

export const cleanChar = (options: {
  readonly raw: string;
  readonly required: boolean;
  readonly maxLength: number | null;
}): Cleaned<string> => {
  const value = pyStrip(options.raw);

  if (value === "") {
    return options.required
      ? Result.fail([REQUIRED_ERROR])
      : Result.succeed("");
  }

  const errors = charValidators(value, options.maxLength);

  return errors.length > 0 ? Result.fail(errors) : Result.succeed(value);
};

const DIGITS = `${PY_DECIMAL_CLASS}+`;

const PY_INT = new RegExp(
  `^${PY_SPACE_CLASS}*([+-]?)(${DIGITS}(?:_${DIGITS})*)${PY_SPACE_CLASS}*$`,
  "u"
);

const DECIMAL_TAIL = new RegExp(`\\.0*${PY_SPACE_CLASS}*$`, "u");

export const pyInt = (text: string): Option.Option<number> => {
  const match = PY_INT.exec(text);

  if (match === null) {
    return Option.none();
  }

  const magnitude = pyDecimalInt((match[2] ?? "").replaceAll("_", ""));

  if (magnitude === null) {
    return Option.none();
  }

  return Option.some(match[1] === "-" ? -magnitude : magnitude);
};

export const cleanInteger = (options: {
  readonly raw: string;
  readonly required: boolean;
  readonly minValue: number | null;
  readonly maxValue: number | null;
  readonly extraMaxValue: number | null;
}): Cleaned<number | null> => {
  if (options.raw === "") {
    return options.required
      ? Result.fail([REQUIRED_ERROR])
      : Result.succeed(null);
  }

  const parsed = pyInt(options.raw.replace(DECIMAL_TAIL, ""));

  if (Option.isNone(parsed)) {
    return Result.fail([INVALID_INTEGER_ERROR]);
  }

  const { value } = parsed;

  const errors = [
    ...(options.extraMaxValue !== null && value > options.extraMaxValue
      ? [STORAGE_LIMIT_ERROR]
      : []),
    ...(options.maxValue !== null && value > options.maxValue
      ? [maxValueError(options.maxValue)]
      : []),
    ...(options.minValue !== null && value < options.minValue
      ? [minValueError(options.minValue)]
      : []),
  ];

  return errors.length > 0 ? Result.fail(errors) : Result.succeed(value);
};

export const cleanChoice = (options: {
  readonly raw: string;
  readonly required: boolean;
  readonly choices: readonly string[];
}): Cleaned<string> => {
  if (options.raw === "") {
    return options.required
      ? Result.fail([REQUIRED_ERROR])
      : Result.succeed("");
  }

  return options.choices.includes(options.raw)
    ? Result.succeed(options.raw)
    : Result.fail([invalidChoiceError(options.raw)]);
};

export const EMAIL_MAX_LENGTH = 320;

const IPV6_LITERAL_MAX_LENGTH = 39;

const UL = "¡-￿";

const USER_PART = new RegExp(
  String.raw`^(?:[-!#$%&'*+/=?^_\x60{}|~0-9A-Z\u0130\u0131]+(?:\.[-!#$%&'*+/=?^_\x60{}|~0-9A-Z\u0130\u0131]+)*$` +
    String.raw`|^"(?:[\x01-\x08\x0b\x0c\x0e-\x1f!#-\[\]-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])*"$)`,
  "iu"
);

const HOSTNAME = `[a-z${UL}0-9](?:[a-z${UL}0-9-]{0,61}[a-z${UL}0-9])?`;

const DOMAIN = `(?:\\.(?!-)[a-z${UL}0-9-]{1,63}(?<!-))*`;

const TLD = `\\.(?!-)(?:[a-z${UL}-]{2,63}|xn--[a-z0-9]{1,59})(?<!-)`;

const DOMAIN_PART = new RegExp(`^${HOSTNAME}${DOMAIN}${TLD}$`, "iu");

const LITERAL = /^\[(?<address>[A-F0-9:.]+)\]$/iu;

const isIpLiteral = (address: string): boolean => {
  if (Option.isSome(parseIpv4Address(address))) {
    return true;
  }

  return (
    pyLength(address) <= IPV6_LITERAL_MAX_LENGTH &&
    Option.isSome(parseIpv6Address(address))
  );
};

export const isValidEmail = (value: string): boolean => {
  if (
    value === "" ||
    !value.includes("@") ||
    pyLength(value) > EMAIL_MAX_LENGTH
  ) {
    return false;
  }

  const at = value.lastIndexOf("@");
  const user = value.slice(0, at);
  const domain = value.slice(at + 1);

  if (!USER_PART.test(user)) {
    return false;
  }

  if (domain === "localhost" || DOMAIN_PART.test(domain)) {
    return true;
  }

  const literal = LITERAL.exec(domain);

  return literal !== null && isIpLiteral(literal.groups?.address ?? "");
};

export const cleanEmail = (raw: string): Cleaned<string> => {
  const value = pyStrip(raw);

  if (value === "") {
    return Result.fail([REQUIRED_ERROR]);
  }

  const errors = [
    ...(isValidEmail(value) ? [] : [INVALID_EMAIL_ERROR]),
    ...charValidators(value, EMAIL_MAX_LENGTH),
  ];

  return errors.length > 0 ? Result.fail(errors) : Result.succeed(value);
};
