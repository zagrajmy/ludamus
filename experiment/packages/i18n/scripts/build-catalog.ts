import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { Result } from "effect";

import { compilePluralForms } from "../src/plural-rule.ts";
import { parsePo } from "../src/po.ts";

const DJANGO_CATALOG = new URL(
  "../../../../src/ludamus/locale/pl/LC_MESSAGES/django.po",
  import.meta.url
);

const GENERATED = new URL("../src/catalog.generated.json", import.meta.url);

const sortedByKey = <Value>(record: Readonly<Record<string, Value>>) =>
  Object.fromEntries(
    Object.entries(record).toSorted(([left], [right]) =>
      left < right ? -1 : left > right ? 1 : 0
    )
  );

const source = process.argv[2] ?? fileURLToPath(DJANGO_CATALOG);

const parsed = parsePo(readFileSync(source, "utf8"));

if (Result.isFailure(parsed)) {
  process.stderr.write(`${source}: ${parsed.failure.message}\n`);
  process.exit(1);
}

const catalog = parsed.success;

const rule = compilePluralForms(catalog.pluralForms);

if (Result.isFailure(rule)) {
  process.stderr.write(`${source}: ${rule.failure.message}\n`);
  process.exit(1);
}

const misfits = Object.entries(catalog.plurals).filter(
  ([, forms]) => forms.length !== rule.success.count
);

if (misfits.length > 0) {
  process.stderr.write(
    `${source}: ${misfits.length} plural entries do not have ${rule.success.count} forms, first: ${misfits[0]?.[0]}\n`
  );
  process.exit(1);
}

writeFileSync(
  GENERATED,
  `${JSON.stringify(
    {
      language: "pl",
      pluralForms: catalog.pluralForms,
      messages: sortedByKey(catalog.messages),
      plurals: sortedByKey(catalog.plurals),
    },
    null,
    2
  )}\n`
);

const contexts = [
  ...Object.keys(catalog.messages),
  ...Object.keys(catalog.plurals),
].filter((key) => key.includes("\u0004")).length;

process.stdout.write(
  `${fileURLToPath(GENERATED)}: ${Object.keys(catalog.messages).length} messages, ${Object.keys(catalog.plurals).length} plurals, ${contexts} with context, ${rule.success.count} plural forms\n`
);
