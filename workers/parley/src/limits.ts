const HTTP_URL = /https?:\/\/[^\s]+/giu;

export function normalizeMessage(input: unknown): string | null {
  if (typeof input !== "string") return null;
  const body = input.replaceAll("\r\n", "\n").trim();
  if (body.length === 0 || [...body].length > 1_000) return null;
  return [...body.matchAll(HTTP_URL)].length <= 5 ? body : null;
}

export function integer(input: unknown): number | null {
  return typeof input === "number" && Number.isSafeInteger(input) && input > 0 ? input : null;
}
