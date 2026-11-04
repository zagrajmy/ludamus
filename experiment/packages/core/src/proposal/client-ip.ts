import { Option } from "effect";

import { pyLength, pyStrip } from "./python-text.js";

const HEXTET_COUNT = 8;

const MAX_IPV6_LENGTH = 45;

const OCTET_MAX = 255;

const DECIMAL_OCTET = /^[0-9]+$/u;

const HEX_HEXTET = /^[0-9A-Fa-f]*$/u;

const parseOctet = (octet: string): Option.Option<number> => {
  if (
    octet === "" ||
    !DECIMAL_OCTET.test(octet) ||
    octet.length > 3 ||
    (octet !== "0" && octet.startsWith("0"))
  ) {
    return Option.none();
  }

  const value = Number(octet);

  return value > OCTET_MAX ? Option.none() : Option.some(value);
};

const parseIpv4 = (text: string): Option.Option<readonly number[]> => {
  if (text === "" || text.includes("/")) {
    return Option.none();
  }

  const octets = text.split(".");

  if (octets.length !== 4) {
    return Option.none();
  }

  const parsed = octets.map(parseOctet);

  return Option.all(parsed);
};

const parseHextet = (hextet: string): Option.Option<number> =>
  HEX_HEXTET.test(hextet) && hextet.length <= 4 && hextet !== ""
    ? Option.some(Number.parseInt(hextet, 16))
    : Option.none();

const splitAtMost = (text: string, limit: number): string[] => {
  const parts = text.split(":");

  return parts.length > limit + 1
    ? [...parts.slice(0, limit), parts.slice(limit).join(":")]
    : parts;
};

const ipv4Hextets = (octets: readonly number[]): readonly [string, string] => {
  const [a = 0, b = 0, c = 0, d = 0] = octets;

  return [(a * 256 + b).toString(16), (c * 256 + d).toString(16)];
};

const layout = (
  parts: readonly string[]
): Option.Option<Readonly<{ hi: number; lo: number; skipped: number }>> => {
  let skipIndex = -1;

  for (let index = 1; index < parts.length - 1; index += 1) {
    if (parts[index] === "") {
      if (skipIndex !== -1) {
        return Option.none();
      }

      skipIndex = index;
    }
  }

  const first = parts[0] ?? "";
  const last = parts.at(-1) ?? "";

  if (skipIndex === -1) {
    return parts.length === HEXTET_COUNT && first !== "" && last !== ""
      ? Option.some({ hi: parts.length, lo: 0, skipped: 0 })
      : Option.none();
  }

  let hi = skipIndex;
  let lo = parts.length - skipIndex - 1;

  if (first === "") {
    hi -= 1;

    if (hi > 0) {
      return Option.none();
    }
  }

  if (last === "") {
    lo -= 1;

    if (lo > 0) {
      return Option.none();
    }
  }

  const skipped = HEXTET_COUNT - (hi + lo);

  return skipped < 1 ? Option.none() : Option.some({ hi, lo, skipped });
};

const parseIpv6Hextets = (text: string): Option.Option<readonly number[]> => {
  if (text === "" || pyLength(text) > MAX_IPV6_LENGTH) {
    return Option.none();
  }

  const parts = splitAtMost(text, HEXTET_COUNT + 1);

  if (parts.length < 3) {
    return Option.none();
  }

  const tail = parts.at(-1) ?? "";

  if (tail.includes(".")) {
    const embedded = parseIpv4(tail);

    if (Option.isNone(embedded)) {
      return Option.none();
    }

    parts.splice(-1, 1, ...ipv4Hextets(embedded.value));
  }

  if (parts.length > HEXTET_COUNT + 1) {
    return Option.none();
  }

  return Option.flatMap(layout(parts), ({ hi, lo, skipped }) =>
    Option.map(
      Option.all([
        ...parts.slice(0, hi).map(parseHextet),
        ...Array.from({ length: skipped }, () => Option.some(0)),
        ...(lo === 0 ? [] : parts.slice(-lo)).map(parseHextet),
      ]),
      (hextets): readonly number[] => hextets
    )
  );
};

const compressHextets = (hextets: readonly string[]): string => {
  let bestStart = -1;
  let bestLength = 0;
  let start = -1;
  let length = 0;

  for (const [index, hextet] of hextets.entries()) {
    if (hextet === "0") {
      length += 1;

      if (start === -1) {
        start = index;
      }

      if (length > bestLength) {
        bestLength = length;
        bestStart = start;
      }
    } else {
      length = 0;
      start = -1;
    }
  }

  if (bestLength <= 1) {
    return hextets.join(":");
  }

  const end = bestStart + bestLength;
  const head = hextets.slice(0, bestStart);
  const rest = hextets.slice(end);

  return [
    ...(bestStart === 0 ? [""] : head),
    "",
    ...(end === hextets.length ? [""] : rest),
  ].join(":");
};

const IPV4_MAPPED_MARKER = 0xff_ff;

const formatIpv6 = (hextets: readonly number[]): string => {
  const isMapped =
    hextets.slice(0, 5).every((hextet) => hextet === 0) &&
    hextets[5] === IPV4_MAPPED_MARKER;

  if (isMapped) {
    const high = hextets[6] ?? 0;
    const low = hextets[7] ?? 0;

    const dotted = [
      Math.floor(high / 256),
      high % 256,
      Math.floor(low / 256),
      low % 256,
    ].join(".");

    return `::ffff:${dotted}`;
  }

  return compressHextets(hextets.map((hextet) => hextet.toString(16)));
};

const parseIpv6 = (text: string): Option.Option<string> => {
  if (text.includes("/")) {
    return Option.none();
  }

  const separator = text.indexOf("%");
  const address = separator === -1 ? text : text.slice(0, separator);
  const scope = separator === -1 ? null : text.slice(separator + 1);

  if (scope !== null && (scope === "" || scope.includes("%"))) {
    return Option.none();
  }

  return Option.map(parseIpv6Hextets(address), (hextets) =>
    scope === null ? formatIpv6(hextets) : `${formatIpv6(hextets)}%${scope}`
  );
};

export const parseIpv4Address = (text: string): Option.Option<string> =>
  Option.map(parseIpv4(text), (octets) => octets.join("."));

export const parseIpv6Address = parseIpv6;

export const parseClientIp = (raw: string): Option.Option<string> => {
  const text = pyStrip(raw);

  return Option.orElse(parseIpv4Address(text), () => parseIpv6(text));
};
