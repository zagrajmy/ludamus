import { readFileSync, statSync, globSync } from "node:fs";
import { resolve } from "node:path";

export type CodeArea = Readonly<{
  label: string;
  old: readonly string[];
  new: readonly string[];
}>;

const repoRoot = resolve(import.meta.dirname, "../../..");

const countLines = (
  patterns: readonly string[]
): { files: number; lines: number } => {
  let files = 0;
  let lines = 0;

  for (const pattern of patterns) {
    for (const path of globSync(pattern, { cwd: repoRoot })) {
      const absolute = resolve(repoRoot, path);

      if (!statSync(absolute).isFile()) {
        continue;
      }

      files += 1;
      lines += readFileSync(absolute, "utf-8")
        .split("\n")
        .filter((line) => line.trim() !== "").length;
    }
  }

  return { files, lines };
};

export const measureCode = (areas: readonly CodeArea[]) =>
  areas.map((area) => ({
    label: area.label,
    new: countLines(area.new),
    old: countLines(area.old),
  }));
