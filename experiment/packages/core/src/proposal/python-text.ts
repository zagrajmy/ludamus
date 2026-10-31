type CodePointRange = readonly [number, number];

const DECIMAL_ZEROS: readonly number[] = [
  0x30, 0x6_60, 0x6_f0, 0x7_c0, 0x9_66, 0x9_e6, 0xa_66, 0xa_e6, 0xb_66, 0xb_e6,
  0xc_66, 0xc_e6, 0xd_66, 0xd_e6, 0xe_50, 0xe_d0, 0xf_20, 0x10_40, 0x10_90,
  0x17_e0, 0x18_10, 0x19_46, 0x19_d0, 0x1a_80, 0x1a_90, 0x1b_50, 0x1b_b0,
  0x1c_40, 0x1c_50, 0xa6_20, 0xa8_d0, 0xa9_00, 0xa9_d0, 0xa9_f0, 0xaa_50,
  0xab_f0, 0xff_10, 0x1_04_a0, 0x1_0d_30, 0x1_0d_40, 0x1_10_66, 0x1_10_f0,
  0x1_11_36, 0x1_11_d0, 0x1_12_f0, 0x1_14_50, 0x1_14_d0, 0x1_16_50, 0x1_16_c0,
  0x1_16_d0, 0x1_16_da, 0x1_17_30, 0x1_18_e0, 0x1_19_50, 0x1_1b_f0, 0x1_1c_50,
  0x1_1d_50, 0x1_1d_a0, 0x1_1f_50, 0x1_61_30, 0x1_6a_60, 0x1_6a_c0, 0x1_6b_50,
  0x1_6d_70, 0x1_cc_f0, 0x1_d7_ce, 0x1_d7_d8, 0x1_d7_e2, 0x1_d7_ec, 0x1_d7_f6,
  0x1_e1_40, 0x1_e2_f0, 0x1_e4_f0, 0x1_e5_f1, 0x1_e9_50, 0x1_fb_f0,
];

const DIGIT_ONLY_RANGES: readonly CodePointRange[] = [
  [0xb2, 0xb3],
  [0xb9, 0xb9],
  [0x13_69, 0x13_71],
  [0x19_da, 0x19_da],
  [0x20_70, 0x20_70],
  [0x20_74, 0x20_79],
  [0x20_80, 0x20_89],
  [0x24_60, 0x24_68],
  [0x24_74, 0x24_7c],
  [0x24_88, 0x24_90],
  [0x24_ea, 0x24_ea],
  [0x24_f5, 0x24_fd],
  [0x24_ff, 0x24_ff],
  [0x27_76, 0x27_7e],
  [0x27_80, 0x27_88],
  [0x27_8a, 0x27_92],
  [0x1_0a_40, 0x1_0a_43],
  [0x1_0e_60, 0x1_0e_68],
  [0x1_10_52, 0x1_10_5a],
  [0x1_f1_00, 0x1_f1_0a],
];

const SPACE_RANGES: readonly CodePointRange[] = [
  [0x9, 0xd],
  [0x1c, 0x20],
  [0x85, 0x85],
  [0xa0, 0xa0],
  [0x16_80, 0x16_80],
  [0x20_00, 0x20_0a],
  [0x20_28, 0x20_29],
  [0x20_2f, 0x20_2f],
  [0x20_5f, 0x20_5f],
  [0x30_00, 0x30_00],
];

const inRanges = (
  ranges: readonly CodePointRange[],
  codePoint: number
): boolean =>
  ranges.some(([low, high]) => low <= codePoint && codePoint <= high);

const escape = (codePoint: number): string => `\\u{${codePoint.toString(16)}}`;

const classOf = (ranges: readonly CodePointRange[]): string =>
  `[${ranges.map(([low, high]) => `${escape(low)}-${escape(high)}`).join("")}]`;

export const PY_DECIMAL_CLASS = classOf(
  DECIMAL_ZEROS.map((zero): CodePointRange => [zero, zero + 9])
);

export const PY_SPACE_CLASS = classOf(SPACE_RANGES);

export const codePoints = (text: string): readonly number[] =>
  Array.from(text, (char) => char.codePointAt(0) ?? 0);

export const pyLength = (text: string): number => codePoints(text).length;

export const pyIsSpace = (codePoint: number): boolean =>
  inRanges(SPACE_RANGES, codePoint);

export const pyDecimalValue = (codePoint: number): number | null => {
  const zero = DECIMAL_ZEROS.find(
    (start) => start <= codePoint && codePoint <= start + 9
  );

  return zero === undefined ? null : codePoint - zero;
};

export const pyIsDigitString = (text: string): boolean => {
  const points = codePoints(text);

  return (
    points.length > 0 &&
    points.every(
      (point) =>
        pyDecimalValue(point) !== null || inRanges(DIGIT_ONLY_RANGES, point)
    )
  );
};

export const pyDecimalInt = (text: string): number | null => {
  const points = codePoints(text);

  if (points.length === 0) {
    return null;
  }

  let value = 0;

  for (const point of points) {
    const digit = pyDecimalValue(point);

    if (digit === null) {
      return null;
    }

    value = value * 10 + digit;
  }

  return value;
};

export const pyStrip = (text: string): string => {
  const points = codePoints(text);
  let start = 0;
  let end = points.length;

  while (start < end && pyIsSpace(points[start] ?? 0)) {
    start += 1;
  }

  while (end > start && pyIsSpace(points[end - 1] ?? 0)) {
    end -= 1;
  }

  return String.fromCodePoint(...points.slice(start, end));
};

export const pySlice = (text: string, length: number): string =>
  [...text].slice(0, length).join("");
