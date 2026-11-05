// Filemail captures raw RFC 5322 messages: long headers are folded and
// non-ASCII words RFC 2047-encoded, so a raw substring match misses a
// subject the moment it carries a Polish letter. Read headers decoded.

const ENCODED_WORD = /=\?([^?]+)\?([bq])\?([^?]*)\?=(?:\s+(?==\?))?/gi;

function decodeWord(charset: string, encoding: string, text: string): string {
  const bytes =
    encoding.toUpperCase() === "B"
      ? Buffer.from(text, "base64")
      : Buffer.from(
          text
            .replace(/_/g, " ")
            .replace(/=([0-9a-f]{2})/gi, (_match, hex: string) =>
              String.fromCharCode(Number.parseInt(hex, 16)),
            ),
          "latin1",
        );
  return new TextDecoder(charset).decode(bytes);
}

export function mailHeaders(raw: string): Record<string, string> {
  const head = raw
    .trimStart()
    .split(/\r?\n\r?\n/, 1)[0]
    .replace(/\r?\n[ \t]+/g, " ");
  const headers: Record<string, string> = {};
  for (const line of head.split(/\r?\n/)) {
    const colon = line.indexOf(":");
    if (colon > 0) {
      headers[line.slice(0, colon).toLowerCase()] = line
        .slice(colon + 1)
        .trim()
        .replace(ENCODED_WORD, (_match, charset: string, encoding: string, text: string) =>
          decodeWord(charset, encoding, text),
        );
    }
  }
  return headers;
}
