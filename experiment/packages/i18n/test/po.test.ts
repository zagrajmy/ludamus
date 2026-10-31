import { Result } from "effect";
import { describe, expect, it } from "vitest";

import { compilePluralForms } from "../src/plural-rule.js";
import { parsePo } from "../src/po.js";

const sample = String.raw`# translator comment
msgid ""
msgstr ""
"Language: pl\n"
"Plural-Forms: nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && "
"(n%100<10 || n%100>=20) ? 1 : 2);\n"

#: some/file.py
#, python-format
msgid "Hello %(name)s"
msgstr "Cześć %(name)s"

msgctxt "menu"
msgid "Open"
msgstr "Otwórz"

#, fuzzy
msgid "Guess"
msgstr "Zgadywanka"

msgid "Untranslated"
msgstr ""

msgid ""
"Line one\n"
"says \"hi\" \\ bye"
msgstr "Linia\tjeden"

msgid "%(n)s cat"
msgid_plural "%(n)s cats"
msgstr[0] "%(n)s kot"
msgstr[1] "%(n)s koty"
msgstr[2] "%(n)s kotów"

#~ msgid "Gone"
#~ msgstr "Nie ma"
`;

describe("parsePo", () => {
  const parsed = Result.getOrThrow(parsePo(sample));

  it("reads the Plural-Forms header", () => {
    expect(parsed.pluralForms).toBe(
      "nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);"
    );
  });

  it("keys context entries apart from bare msgids", () => {
    expect(parsed.messages).toEqual({
      "Hello %(name)s": "Cześć %(name)s",
      'Line one\nsays "hi" \\ bye': "Linia\tjeden",
      "menu\u0004Open": "Otwórz",
    });
  });

  it("drops fuzzy, untranslated and obsolete entries like msgfmt", () => {
    expect(Object.keys(parsed.messages)).not.toContain("Guess");
    expect(Object.keys(parsed.messages)).not.toContain("Untranslated");
    expect(Object.keys(parsed.messages)).not.toContain("Gone");
  });

  it("collects every plural form in order", () => {
    expect(parsed.plurals).toEqual({
      "%(n)s cat": ["%(n)s kot", "%(n)s koty", "%(n)s kotów"],
    });
  });

  it("names the line of a syntax error", () => {
    const broken = parsePo('msgid "a"\nmsgstr "b"\nwhat is this\n');
    expect(Result.isFailure(broken)).toBe(true);
    expect(
      Result.match(broken, {
        onFailure: (error) => error.message,
        onSuccess: () => "",
      })
    ).toBe("line 3: expected a keyword or a quoted string, got `what is this`");
  });

  it("rejects an unterminated string", () => {
    expect(Result.isFailure(parsePo('msgid "a\nmsgstr "b"\n'))).toBe(true);
  });
});

describe("compilePluralForms", () => {
  const select = (header: string, count: number) =>
    Result.match(compilePluralForms(header), {
      onFailure: (error) => error.message,
      onSuccess: (rule) => rule.select(count),
    });

  const django =
    "nplurals=4; plural=(n==1 ? 0 : (n%10>=2 && n%10<=4) && (n%100<12 || n%100>14) ? 1 : n!=1 && (n%10>=0 && n%10<=1) || (n%10>=5 && n%10<=9) || (n%100>=12 && n%100<=14) ? 2 : 3);";

  it("evaluates the catalog's Polish rule like gettext", () => {
    expect(
      [1, 2, 4, 5, 11, 12, 14, 21, 22, 25, 102, 112, 0].map((n) =>
        select(django, n)
      )
    ).toEqual([0, 1, 1, 2, 2, 2, 2, 2, 1, 2, 1, 2, 2]);
  });

  it("reports the number of forms", () => {
    expect(
      Result.map(compilePluralForms(django), (rule) => rule.count)
    ).toEqual(Result.succeed(4));
  });

  it("evaluates the English rule", () => {
    expect(
      [0, 1, 2].map((n) => select("nplurals=2; plural=(n != 1);", n))
    ).toEqual([1, 0, 1]);
  });

  it("refuses an expression it cannot read", () => {
    expect(select("nplurals=2; plural=(n !! 1);", 1)).toBe(
      "Plural-Forms: unexpected `!` at offset 3 in `(n !! 1)`"
    );
    expect(select("plural=n;", 1)).toBe(
      "Plural-Forms: missing nplurals in `plural=n;`"
    );
  });
});
