import { Schema } from "effect";

import { pyLength, pyStrip } from "./python-text.js";

export const FieldType = Schema.Literals([
  "text",
  "select",
  "checkbox",
  "discord",
]);

export type FieldType = typeof FieldType.Type;

export const OrganizerFieldOption = Schema.Struct({
  label: Schema.String,
  order: Schema.Int,
  pk: Schema.Int,
  value: Schema.String,
});

export type OrganizerFieldOption = typeof OrganizerFieldOption.Type;

export const OrganizerField = Schema.Struct({
  allowCustom: Schema.Boolean,
  fieldType: FieldType,
  helpText: Schema.String,
  icon: Schema.String,
  isMultiple: Schema.Boolean,
  isPublic: Schema.Boolean,
  isRequired: Schema.Boolean,
  maxLength: Schema.Int,
  name: Schema.String,
  options: Schema.Array(OrganizerFieldOption),
  order: Schema.Int,
  pk: Schema.Int,
  question: Schema.String,
  showOnCards: Schema.Boolean,
  slug: Schema.String,
});

export type OrganizerField = typeof OrganizerField.Type;

export const FieldRequirement = Schema.Struct({
  field: OrganizerField,
  isRequired: Schema.Boolean,
});

export type FieldRequirement = typeof FieldRequirement.Type;

export const FieldAnswer = Schema.Union([
  Schema.String,
  Schema.Array(Schema.String),
  Schema.Boolean,
]);

export type FieldAnswer = typeof FieldAnswer.Type;

export const BLANK_CHOICE: readonly [string, string] = ["", "—"];

export const WRITE_IN_SEPARATOR = ";";

const isAnswerList = (value: FieldAnswer | null): value is readonly string[] =>
  Array.isArray(value);

export const offersCustomInput = (field: OrganizerField): boolean =>
  field.allowCustom && field.fieldType !== "checkbox";

const compareCodePoints = (a: string, b: string): number => {
  if (a === b) {
    return 0;
  }

  return a < b ? -1 : 1;
};

export const sortedOptions = (
  field: OrganizerField
): readonly OrganizerFieldOption[] =>
  field.options.toSorted((a, b) =>
    a.order === b.order
      ? compareCodePoints(a.label, b.label)
      : a.order - b.order
  );

export const fieldChoices = (
  field: OrganizerField
): readonly (readonly [string, string])[] => [
  BLANK_CHOICE,
  ...sortedOptions(field).map((option): readonly [string, string] => [
    option.value,
    option.label,
  ]),
];

export const lengthLimit = (field: OrganizerField): number | null =>
  field.maxLength || null;

export const controlRequired = (requirement: FieldRequirement): boolean =>
  requirement.isRequired && !offersCustomInput(requirement.field);

export const personalFieldRequirements = (
  fields: readonly OrganizerField[]
): readonly FieldRequirement[] =>
  fields.map((field) => ({ field, isRequired: field.isRequired }));

export const ControlKind = Schema.Literals([
  "multipleChoice",
  "choice",
  "boolean",
  "text",
]);

export type ControlKind = typeof ControlKind.Type;

export const FieldControl = Schema.Struct({
  choices: Schema.NullOr(
    Schema.Array(Schema.Tuple([Schema.String, Schema.String]))
  ),
  key: Schema.String,
  kind: ControlKind,
  maxLength: Schema.NullOr(Schema.Int),
  required: Schema.Boolean,
});

export type FieldControl = typeof FieldControl.Type;

export const FieldControls = Schema.Struct({
  controls: Schema.Array(FieldControl),
  pairCheckedKeys: Schema.Array(Schema.String),
});

export type FieldControls = typeof FieldControls.Type;

const mainControl = (
  key: string,
  requirement: FieldRequirement
): FieldControl => {
  const { field } = requirement;
  const required = controlRequired(requirement);

  if (field.fieldType === "select") {
    const choices = fieldChoices(field);

    return field.isMultiple
      ? {
          choices: choices.slice(1),
          key,
          kind: "multipleChoice",
          maxLength: null,
          required,
        }
      : { choices, key, kind: "choice", maxLength: null, required };
  }

  if (field.fieldType === "checkbox") {
    return {
      choices: null,
      key,
      kind: "boolean",
      maxLength: null,
      required: false,
    };
  }

  return {
    choices: null,
    key,
    kind: "text",
    maxLength: lengthLimit(field),
    required,
  };
};

export const resolveFieldControls = (options: {
  readonly prefix: string;
  readonly pairs: readonly FieldRequirement[];
}): FieldControls => {
  const controls = new Map<string, FieldControl>();

  for (const requirement of options.pairs) {
    const key = `${options.prefix}_${requirement.field.slug}`;
    controls.set(key, mainControl(key, requirement));

    if (offersCustomInput(requirement.field)) {
      const customKey = `${key}_custom`;
      controls.set(customKey, {
        choices: null,
        key: customKey,
        kind: "text",
        maxLength: lengthLimit(requirement.field),
        required: false,
      });
    }
  }

  return {
    controls: [...controls.values()],
    pairCheckedKeys: options.pairs
      .filter((pair) => pair.isRequired && offersCustomInput(pair.field))
      .map((pair) => `${options.prefix}_${pair.field.slug}`),
  };
};

export const FieldValidation = Schema.Struct({
  cleaned: Schema.Record(Schema.String, FieldAnswer),
  errors: Schema.Record(Schema.String, Schema.Array(Schema.String)),
  valid: Schema.Boolean,
});

export type FieldValidation = typeof FieldValidation.Type;

type CleanOutcome =
  | { readonly ok: true; readonly value: FieldAnswer }
  | { readonly ok: false; readonly codes: readonly string[] };

const lastValue = (values: readonly string[] | undefined): string | null =>
  values === undefined ? null : (values.at(-1) ?? null);

const isChoice = (control: FieldControl, value: string): boolean =>
  (control.choices ?? []).some(([choice]) => choice === value);

const cleanText = (control: FieldControl, raw: string | null): CleanOutcome => {
  const value = raw === null ? "" : pyStrip(raw);

  if (value === "") {
    return control.required
      ? { codes: ["required"], ok: false }
      : { ok: true, value };
  }

  const codes = [
    ...(control.maxLength !== null && pyLength(value) > control.maxLength
      ? ["max_length"]
      : []),
    ...(value.includes("\u0000") ? ["null_characters_not_allowed"] : []),
  ];

  return codes.length > 0 ? { codes, ok: false } : { ok: true, value };
};

const cleanControl = (
  control: FieldControl,
  data: Readonly<Record<string, readonly string[]>>
): CleanOutcome => {
  const values = data[control.key];

  switch (control.kind) {
    case "text": {
      return cleanText(control, lastValue(values));
    }

    case "choice": {
      const value = lastValue(values) ?? "";

      if (value === "") {
        return control.required
          ? { codes: ["required"], ok: false }
          : { ok: true, value };
      }

      return isChoice(control, value)
        ? { ok: true, value }
        : { codes: ["invalid_choice"], ok: false };
    }

    case "multipleChoice": {
      const chosen = values ?? [];

      if (chosen.length === 0) {
        return control.required
          ? { codes: ["required"], ok: false }
          : { ok: true, value: [] };
      }

      return [...new Set(chosen)].every((value) => isChoice(control, value))
        ? { ok: true, value: chosen }
        : { codes: ["invalid_choice"], ok: false };
    }

    case "boolean": {
      const raw = lastValue(values);

      if (values === undefined || raw === null) {
        return { ok: true, value: false };
      }

      const lowered = raw.toLowerCase();

      return {
        ok: true,
        value: lowered === "false" ? false : lowered === "true" || raw !== "",
      };
    }
  }
};

export const isTruthyAnswer = (
  value: FieldAnswer | null | undefined
): boolean => {
  if (typeof value === "string") {
    return value !== "";
  }

  if (typeof value === "boolean") {
    return value;
  }

  return value !== null && value !== undefined && value.length > 0;
};

export const validateFieldAnswers = (options: {
  readonly prefix: string;
  readonly pairs: readonly FieldRequirement[];
  readonly data: Readonly<Record<string, readonly string[]>>;
}): FieldValidation => {
  const { controls, pairCheckedKeys } = resolveFieldControls(options);
  const cleaned = new Map<string, FieldAnswer>();
  const errors = new Map<string, string[]>();

  for (const control of controls) {
    const outcome = cleanControl(control, options.data);

    if (outcome.ok) {
      cleaned.set(control.key, outcome.value);
    } else {
      errors.set(control.key, [...outcome.codes]);
    }
  }

  for (const key of pairCheckedKeys) {
    if (
      isTruthyAnswer(cleaned.get(key)) ||
      isTruthyAnswer(cleaned.get(`${key}_custom`))
    ) {
      continue;
    }

    errors.set(key, [...(errors.get(key) ?? []), "custom_answer_required"]);
    cleaned.delete(key);
  }

  return {
    cleaned: Object.fromEntries(cleaned),
    errors: Object.fromEntries(errors),
    valid: errors.size === 0,
  };
};

export const isEmptyAnswer = (value: FieldAnswer | null): boolean => {
  if (typeof value === "string") {
    return pyStrip(value) === "";
  }

  if (Array.isArray(value)) {
    return value.length === 0;
  }

  return value === null;
};

export const mergeCustom = (options: {
  readonly chosen: FieldAnswer | null;
  readonly custom: string;
  readonly isMultiple: boolean;
}): FieldAnswer => {
  const { chosen, custom } = options;

  if (typeof chosen === "boolean") {
    return chosen;
  }

  if (!options.isMultiple) {
    return chosen !== null && isTruthyAnswer(chosen) ? chosen : custom;
  }

  const values: string[] = isAnswerList(chosen) ? [...chosen] : [];

  for (const part of custom.split(WRITE_IN_SEPARATOR).map(pyStrip)) {
    if (part !== "" && !values.includes(part)) {
      values.push(part);
    }
  }

  return values;
};

export const splitStored = (options: {
  readonly stored: FieldAnswer | null;
  readonly known: readonly string[];
  readonly isMultiple: boolean;
}): readonly [string | readonly string[], string] => {
  const { stored, known, isMultiple } = options;

  if (stored === null || typeof stored === "boolean") {
    return [isMultiple ? [] : "", ""];
  }

  const values = typeof stored === "string" ? [stored] : stored;
  const chosen = values.filter((value) => known.includes(value));

  const custom = values
    .filter((value) => !known.includes(value))
    .join(`${WRITE_IN_SEPARATOR} `);

  if (isMultiple) {
    return [chosen, custom];
  }

  return [chosen[0] ?? "", custom];
};

const PRINTABLE_EXCLUDED =
  /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]/u;

const pyEscape = (char: string): string => {
  const point = char.codePointAt(0) ?? 0;

  const named: Readonly<Record<string, string>> = {
    "\t": "\\t",
    "\n": "\\n",
    "\r": "\\r",
    "\\": "\\\\",
  };

  const known = named[char];

  if (known !== undefined) {
    return known;
  }

  if (char === " " || !PRINTABLE_EXCLUDED.test(char)) {
    return char;
  }

  if (point < 0x1_00) {
    return `\\x${point.toString(16).padStart(2, "0")}`;
  }

  if (point < 0x1_00_00) {
    return `\\u${point.toString(16).padStart(4, "0")}`;
  }

  return `\\U${point.toString(16).padStart(8, "0")}`;
};

const pyRepr = (text: string): string => {
  const quote = text.includes("'") && !text.includes('"') ? '"' : "'";

  const body = Array.from(text, (char) =>
    char === quote ? `\\${quote}` : pyEscape(char)
  ).join("");

  return `${quote}${body}${quote}`;
};

export const pyStr = (value: FieldAnswer): string => {
  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "boolean") {
    return value ? "True" : "False";
  }

  return `[${value.map(pyRepr).join(", ")}]`;
};

const customText = (value: FieldAnswer | undefined): string =>
  value === undefined || !isTruthyAnswer(value) ? "" : pyStr(value);

export const answeredValue = (options: {
  readonly prefix: string;
  readonly field: OrganizerField;
  readonly cleaned: Readonly<Record<string, FieldAnswer>>;
}): FieldAnswer => {
  const key = `${options.prefix}_${options.field.slug}`;
  const value = options.cleaned[key];

  if (!offersCustomInput(options.field)) {
    return value ?? "";
  }

  return mergeCustom({
    chosen: value ?? null,
    custom: customText(options.cleaned[`${key}_custom`]),
    isMultiple: options.field.isMultiple,
  });
};

export const unfoldCustomAnswers = (options: {
  readonly stored: Readonly<Record<string, FieldAnswer>>;
  readonly fields: readonly OrganizerField[];
  readonly prefix: string;
}): Readonly<Record<string, FieldAnswer>> => {
  const keys = new Set(
    options.fields.map((field) => `${options.prefix}_${field.slug}`)
  );

  const initial = new Map(Object.entries(options.stored));

  for (const field of options.fields) {
    const key = `${options.prefix}_${field.slug}`;
    const value = initial.get(key);

    if (
      field.fieldType !== "select" ||
      value === undefined ||
      typeof value === "boolean"
    ) {
      continue;
    }

    const [chosen, custom] = splitStored({
      isMultiple: field.isMultiple,
      known: field.options.map((option) => option.value),
      stored: value,
    });

    initial.set(key, chosen);
    const customKey = `${key}_custom`;

    if (custom !== "" && field.allowCustom && !keys.has(customKey)) {
      initial.set(customKey, custom);
    }
  }

  return Object.fromEntries(initial);
};

export const foldCustomAnswers = (options: {
  readonly cleaned: Readonly<Record<string, FieldAnswer>>;
  readonly fields: readonly OrganizerField[];
  readonly prefix: string;
}): Readonly<Record<string, FieldAnswer>> => {
  const keys = new Set(
    options.fields.map((field) => `${options.prefix}_${field.slug}`)
  );

  const companions = new Set(
    options.fields
      .filter(offersCustomInput)
      .map((field) => `${options.prefix}_${field.slug}_custom`)
      .filter((key) => !keys.has(key))
  );

  const folded = new Map(
    Object.entries(options.cleaned).filter(([key]) => !companions.has(key))
  );

  for (const field of options.fields) {
    const key = `${options.prefix}_${field.slug}`;
    const value = folded.get(key);

    if (!field.allowCustom || value === undefined) {
      continue;
    }

    const customKey = `${key}_custom`;
    folded.set(
      key,
      mergeCustom({
        chosen: value,
        custom: keys.has(customKey)
          ? ""
          : customText(options.cleaned[customKey]),
        isMultiple: field.isMultiple,
      })
    );
  }

  return Object.fromEntries(folded);
};
