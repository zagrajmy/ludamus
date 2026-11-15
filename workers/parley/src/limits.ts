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

export const DAY_MS = 86_400_000;
// Every message, in every kind of room, is deleted for good a year after it
// was written.
// NOTE: Django clears its reports' copies on PARLEY_MESSAGE_LIFETIME in
// src/ludamus/specs/parley.py; keep the two equal.
export const MESSAGE_LIFETIME_MS = 365 * DAY_MS;

// Anything written at or before this instant has outlived its year.
export function retentionCutoff(): number {
  return Date.now() - MESSAGE_LIFETIME_MS;
}
