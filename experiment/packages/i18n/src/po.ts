import { Result, Schema } from "effect";

export class PoSyntaxError extends Schema.TaggedError<PoSyntaxError>()(
  "PoSyntaxError",
  {
    line: Schema.Number,
    reason: Schema.String,
  }
) {
  override get message(): string {
    return `line ${this.line}: ${this.reason}`;
  }
}

export interface PoCatalog {
  readonly messages: Readonly<Record<string, string>>;
  readonly plurals: Readonly<Record<string, readonly string[]>>;
  readonly pluralForms: string;
}

interface Entry {
  context: string | undefined;
  id: string | undefined;
  idPlural: string | undefined;
  translations: string[];
  fuzzy: boolean;
}

type Field =
  | { readonly kind: "msgctxt" }
  | { readonly kind: "msgid" }
  | { readonly kind: "msgid_plural" }
  | { readonly kind: "msgstr"; readonly index: number };

const CONTEXT_SEPARATOR = "\u0004";

const KEYWORD_LINE =
  /^(msgctxt|msgid_plural|msgid|msgstr)(?:\[(\d+)\])?\s+(".*)$/;

const STRING_LINE = /^".*$/;

const ESCAPE_LETTERS = '\\"abfnrtv';

const ESCAPED_CHARACTERS = '\\"\u0007\b\f\n\r\t\v';

const unquote = (quoted: string): Result.Result<string, string> => {
  const trimmed = quoted.trimEnd();

  if (
    trimmed.length < 2 ||
    !trimmed.startsWith('"') ||
    !trimmed.endsWith('"')
  ) {
    return Result.fail(`unterminated string ${trimmed}`);
  }

  const body = trimmed.slice(1, -1);
  let text = "";
  let position = 0;

  while (position < body.length) {
    const character = body.charAt(position);

    if (character === '"') {
      return Result.fail(`unescaped quote in ${trimmed}`);
    }

    if (character !== "\\") {
      text += character;
      position += 1;
      continue;
    }

    const escaped = body.charAt(position + 1);

    const escapeIndex = escaped === "" ? -1 : ESCAPE_LETTERS.indexOf(escaped);

    if (escapeIndex < 0) {
      return Result.fail(`unknown escape \\${escaped} in ${trimmed}`);
    }

    text += ESCAPED_CHARACTERS.charAt(escapeIndex);
    position += 2;
  }

  return Result.succeed(text);
};

const emptyEntry = (): Entry => ({
  context: undefined,
  fuzzy: false,
  id: undefined,
  idPlural: undefined,
  translations: [],
});

const appendTo = (entry: Entry, field: Field, text: string) => {
  switch (field.kind) {
    case "msgctxt": {
      entry.context = (entry.context ?? "") + text;
      break;
    }

    case "msgid": {
      entry.id = (entry.id ?? "") + text;
      break;
    }

    case "msgid_plural": {
      entry.idPlural = (entry.idPlural ?? "") + text;
      break;
    }

    case "msgstr": {
      entry.translations[field.index] =
        (entry.translations[field.index] ?? "") + text;
      break;
    }
  }
};

const fieldOf = (keyword: string, index: string | undefined): Field => {
  if (keyword === "msgstr") {
    return { index: index === undefined ? 0 : Number(index), kind: "msgstr" };
  }

  if (keyword === "msgctxt") {
    return { kind: "msgctxt" };
  }

  return keyword === "msgid_plural"
    ? { kind: "msgid_plural" }
    : { kind: "msgid" };
};

const pluralFormsOf = (header: string) => {
  for (const line of header.split("\n")) {
    const separator = line.indexOf(":");

    if (
      separator > 0 &&
      line.slice(0, separator).trim().toLowerCase() === "plural-forms"
    ) {
      return line.slice(separator + 1).trim();
    }
  }

  return "";
};

export const parsePo = (
  text: string
): Result.Result<PoCatalog, PoSyntaxError> => {
  const entries: Entry[] = [];
  let entry = emptyEntry();
  let field: Field | undefined;
  const lines = text.split(/\r?\n/);

  const finish = () => {
    if (entry.id !== undefined) {
      entries.push(entry);
    }

    entry = emptyEntry();
    field = undefined;
  };

  for (const [offset, raw] of lines.entries()) {
    const line = raw.trim();

    const fail = (reason: string) =>
      Result.fail(new PoSyntaxError({ line: offset + 1, reason }));

    if (line === "") {
      if (entry.id !== undefined) {
        finish();
      }

      continue;
    }

    if (line.startsWith("#")) {
      if (entry.id !== undefined || line.startsWith("#~")) {
        finish();
      }

      if (
        line.startsWith("#,") &&
        line
          .slice(2)
          .split(",")
          .some((flag) => flag.trim() === "fuzzy")
      ) {
        entry.fuzzy = true;
      }

      continue;
    }

    const keyword = KEYWORD_LINE.exec(line);

    if (keyword !== null) {
      const next = fieldOf(keyword[1] ?? "", keyword[2]);
      const startsEntry = next.kind === "msgid" || next.kind === "msgctxt";

      if (startsEntry && entry.id !== undefined) {
        finish();
      }

      const value = unquote(keyword[3] ?? "");

      if (Result.isFailure(value)) {
        return fail(value.failure);
      }

      field = next;
      appendTo(entry, field, value.success);
      continue;
    }

    if (STRING_LINE.test(line)) {
      if (field === undefined) {
        return fail(`string outside an entry: \`${line}\``);
      }

      const value = unquote(line);

      if (Result.isFailure(value)) {
        return fail(value.failure);
      }

      appendTo(entry, field, value.success);
      continue;
    }

    return fail(`expected a keyword or a quoted string, got \`${line}\``);
  }

  finish();

  const messages: Record<string, string> = {};
  const plurals: Record<string, readonly string[]> = {};
  let pluralForms = "";

  for (const { context, fuzzy, id, idPlural, translations } of entries) {
    if (id === "" && context === undefined) {
      pluralForms = pluralFormsOf(translations[0] ?? "");
      continue;
    }

    const forms = Array.from(translations, (form) => form ?? "");

    if (
      fuzzy ||
      id === undefined ||
      forms.length === 0 ||
      forms.some((form) => form === "")
    ) {
      continue;
    }

    const key =
      context === undefined ? id : `${context}${CONTEXT_SEPARATOR}${id}`;

    if (idPlural === undefined) {
      messages[key] = forms[0] ?? "";
    } else {
      plurals[key] = forms;
    }
  }

  return Result.succeed({ messages, pluralForms, plurals });
};
