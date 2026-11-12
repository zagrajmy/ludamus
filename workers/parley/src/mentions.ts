const MENTION = /<@(\d+)>/gu;

export const MAX_MENTIONS = 20;

// NOTE: a 1,000-character body holds at most 200 "<@n>"; a longer list
const MAX_ASKED = 200;

export function mentionsIn({
  allowed,
  asked,
  body,
}: {
  allowed: ReadonlySet<string>;
  asked: unknown;
  body: string;
}): string[] {
  if (!Array.isArray(asked) || asked.length > MAX_ASKED) return [];
  const mentions: string[] = [];
  for (const [, id] of body.matchAll(MENTION)) {
    if (mentions.length === MAX_MENTIONS) break;
    if (allowed.has(id!) && asked.includes(id) && !mentions.includes(id!)) mentions.push(id!);
  }
  return mentions;
}
