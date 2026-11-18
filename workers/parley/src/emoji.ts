// One emoji as a person would pick it: a pictograph with its skin tone,
// presentation selector or tag sequence, joined pictographs (👩‍🚀), a flag
// (two regional indicators) or a keycap. Nothing else, and nothing long.
const ONE_EMOJI =
  /^(?:\p{Regional_Indicator}{2}|[#*0-9]️?⃣|\p{Extended_Pictographic}(?:\p{Emoji_Modifier}|️|[\u{E0020}-\u{E007F}]+)?(?:‍\p{Extended_Pictographic}(?:\p{Emoji_Modifier}|️)?)*)$/u;

// The longest family and flag sequences stay well under this.
const MAX_LENGTH = 32;

export function isEmoji(value: unknown): value is string {
  return typeof value === "string" && value.length <= MAX_LENGTH && ONE_EMOJI.test(value);
}
