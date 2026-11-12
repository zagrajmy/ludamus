const MENTION = /<@(\d+)>/gu;

export const MAX_MENTIONS = 20;

export function mentionsIn(body: string, input: unknown, allowed: ReadonlySet<string>): string[] {
  if (!Array.isArray(input)) return [];
  const written = new Set([...body.matchAll(MENTION)].map((match) => match[1]));
  return [...new Set(input)]
    .filter((id): id is string => typeof id === "string" && written.has(id) && allowed.has(id))
    .slice(0, MAX_MENTIONS);
}
