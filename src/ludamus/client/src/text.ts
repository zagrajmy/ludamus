// Text folding shared by the page's search affordances, so typing "wlodarczyk"
// finds "Włodarczyk" wherever you type it.

const COMBINING_MARKS = /[̀-ͯ]/g;

// Letters NFD leaves whole: their diacritic is part of the glyph, not a mark
// that decomposition can strip.
const NON_DECOMPOSING_MAP: Record<string, string> = {
  æ: "ae",
  đ: "d",
  ħ: "h",
  ı: "i",
  ł: "l",
  ø: "o",
  œ: "oe",
  ß: "ss",
};

/** Lowercase and strip diacritics, for comparing what a person typed. */
const normalizeText = (value: string): string =>
  value
    .toLowerCase()
    .replaceAll(/[łøđħıœæß]/g, (char) => NON_DECOMPOSING_MAP[char] ?? char)
    .normalize("NFD")
    .replaceAll(COMBINING_MARKS, "");

export { normalizeText };
