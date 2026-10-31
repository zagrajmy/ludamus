import { Marked } from "marked";

const renderer = new Marked({ async: false, gfm: true });

const entities: Readonly<Record<string, string>> = {
  "&#39;": "'",
  "&amp;": "&",
  "&gt;": ">",
  "&lt;": "<",
  "&quot;": '"',
};

export const renderMarkdown = (source: string) =>
  renderer.parse(source, { async: false });

export const markdownToPlainText = (source: string) =>
  source === ""
    ? ""
    : renderMarkdown(source)
        .replaceAll(/<[^>]*>/gu, "")
        .replaceAll(
          /&(?:#39|amp|gt|lt|quot);/gu,
          (entity) => entities[entity] ?? entity
        )
        .trim();

const ALLOWED_TAGS = new Set([
  "a",
  "abbr",
  "b",
  "blockquote",
  "br",
  "code",
  "del",
  "em",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "i",
  "li",
  "ol",
  "p",
  "pre",
  "strong",
  "ul",
]);

const ALLOWED_ATTRIBUTES: Readonly<Record<string, ReadonlySet<string>>> = {
  a: new Set(["href", "title"]),
  abbr: new Set(["title"]),
};

const DROPPED_WITH_CONTENT = new Set(["script", "style"]);

const URL_ATTRIBUTES = new Set(["href"]);

const SAFE_SCHEMES = new Set([
  "bitcoin",
  "ftp",
  "ftps",
  "geo",
  "http",
  "https",
  "im",
  "irc",
  "ircs",
  "magnet",
  "mailto",
  "mms",
  "mx",
  "news",
  "nntp",
  "openpgp4fpr",
  "sip",
  "sms",
  "smsto",
  "ssh",
  "tel",
  "url",
  "webcal",
  "wtai",
  "xmpp",
]);

const VOID_TAGS = new Set(["br", "hr"]);

const namedEntities: Readonly<Record<string, string>> = {
  amp: "&",
  apos: "'",
  colon: ":",
  gt: ">",
  lt: "<",
  nbsp: " ",
  newline: "\n",
  quot: '"',
  tab: "\t",
};

const decodeEntities = (value: string) =>
  value.replaceAll(
    /&(#x[0-9a-f]+|#\d+|[a-z]+);?/giu,
    (entity: string, body: string) => {
      if (body.startsWith("#x") || body.startsWith("#X")) {
        return String.fromCodePoint(Number.parseInt(body.slice(2), 16));
      }

      if (body.startsWith("#")) {
        return String.fromCodePoint(Number.parseInt(body.slice(1), 10));
      }

      return namedEntities[body.toLowerCase()] ?? entity;
    }
  );

const escapeText = (value: string) =>
  value.replaceAll("<", "&lt;").replaceAll(">", "&gt;");

const escapeAttribute = (value: string) =>
  value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");

const isSafeUrl = (raw: string) => {
  const compact = decodeEntities(raw).replaceAll(/[\s\u0000-\u001F]/gu, "");
  const scheme = /^([a-z][a-z0-9+.-]*):/iu.exec(compact)?.[1];

  return scheme === undefined || SAFE_SCHEMES.has(scheme.toLowerCase());
};

type Attribute = Readonly<{ name: string; value: string }>;

const attributePattern =
  /([^\s"'>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/gu;

const parseAttributes = (source: string): readonly Attribute[] =>
  [...source.matchAll(attributePattern)].map((match) => ({
    name: (match[1] ?? "").toLowerCase(),
    value: match[2] ?? match[3] ?? match[4] ?? "",
  }));

const keptAttributes = (tag: string, source: string) => {
  const allowed = ALLOWED_ATTRIBUTES[tag];

  if (allowed === undefined) {
    return "";
  }

  const kept = parseAttributes(source).filter(
    (attribute) =>
      allowed.has(attribute.name) &&
      (!URL_ATTRIBUTES.has(attribute.name) || isSafeUrl(attribute.value))
  );

  const rendered = kept.map(
    (attribute) =>
      ` ${attribute.name}="${escapeAttribute(decodeEntities(attribute.value))}"`
  );

  return tag === "a"
    ? `${rendered.join("")} rel="noopener noreferrer"`
    : rendered.join("");
};

const tagPattern =
  /<!--[\s\S]*?(?:-->|$)|<(\/?)([a-zA-Z][a-zA-Z0-9-]*)((?:[^>"']|"[^"]*"|'[^']*')*)>/gu;

export const sanitizeHtml = (html: string) => {
  let output = "";
  let cursor = 0;
  let skippingUntil = "";

  for (const match of html.matchAll(tagPattern)) {
    const index = match.index;
    const text = html.slice(cursor, index);
    cursor = index + match[0].length;

    if (skippingUntil === "") {
      output += escapeText(text);
    }

    const tag = (match[2] ?? "").toLowerCase();
    const isClosing = match[1] === "/";

    if (tag === "") {
      continue;
    }

    if (skippingUntil !== "") {
      if (isClosing && tag === skippingUntil) {
        skippingUntil = "";
      }

      continue;
    }

    if (DROPPED_WITH_CONTENT.has(tag)) {
      if (!isClosing) {
        skippingUntil = tag;
      }

      continue;
    }

    if (!ALLOWED_TAGS.has(tag)) {
      continue;
    }

    if (isClosing) {
      output += VOID_TAGS.has(tag) ? "" : `</${tag}>`;
    } else {
      output += `<${tag}${keptAttributes(tag, match[3] ?? "")}>`;
    }
  }

  if (skippingUntil === "") {
    output += escapeText(html.slice(cursor));
  }

  return output;
};

const loneTilde = /(?<![~\\])~(?!~)/gu;

const tildeStandIn = "";

const safeRenderer = new Marked({ async: false, breaks: true, gfm: true });

export const renderSafeMarkdown = (source: string) =>
  source === ""
    ? ""
    : sanitizeHtml(
        safeRenderer
          .parse(source.replaceAll(loneTilde, tildeStandIn), { async: false })
          .replaceAll(tildeStandIn, "~")
          .replaceAll("%EE%80%80", "~")
      );

const SUMMARY_WORDS = 20;

export const markdownSummary = (source: string) => {
  const words = decodeEntities(
    renderSafeMarkdown(source)
      .replaceAll(/<(?:br|\/p|\/li|\/h\d)\b[^>]*>/gu, " ")
      .replaceAll(/<[^>]*>/gu, "")
  )
    .split(/\s+/u)
    .filter((word) => word !== "");

  return words.length > SUMMARY_WORDS
    ? `${words.slice(0, SUMMARY_WORDS).join(" ")}…`
    : words.join(" ");
};
