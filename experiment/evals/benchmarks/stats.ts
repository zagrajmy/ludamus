export const percentile = (sorted: ReadonlyArray<number>, fraction: number): number => {
  if (sorted.length === 0) {
    return Number.NaN;
  }

  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(fraction * sorted.length) - 1));

  return sorted[index] ?? Number.NaN;
};

export const summarize = (samples: ReadonlyArray<number>) => {
  const sorted = [...samples].sort((a, b) => a - b);
  const total = sorted.reduce((sum, value) => sum + value, 0);

  return {
    count: sorted.length,
    max: sorted.at(-1) ?? Number.NaN,
    mean: sorted.length === 0 ? Number.NaN : total / sorted.length,
    min: sorted[0] ?? Number.NaN,
    p50: percentile(sorted, 0.5),
    p95: percentile(sorted, 0.95),
    p99: percentile(sorted, 0.99),
  };
};

export type Summary = ReturnType<typeof summarize>;
