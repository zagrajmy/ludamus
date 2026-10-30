import { readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

import { globSync } from "node:fs";

export type CodeArea = Readonly<{ label: string; old: ReadonlyArray<string>; new: ReadonlyArray<string> }>;

const repoRoot = resolve(import.meta.dirname, "../../..");

const countLines = (patterns: ReadonlyArray<string>): { files: number; lines: number } => {
  let files = 0;
  let lines = 0;

  for (const pattern of patterns) {
    for (const path of globSync(pattern, { cwd: repoRoot })) {
      const absolute = resolve(repoRoot, path);

      if (!statSync(absolute).isFile()) {
        continue;
      }

      files += 1;
      lines += readFileSync(absolute, "utf8").split("\n").filter((line) => line.trim() !== "").length;
    }
  }

  return { files, lines };
};

export const measureCode = (areas: ReadonlyArray<CodeArea>) =>
  areas.map((area) => ({
    label: area.label,
    new: countLines(area.new),
    old: countLines(area.old),
  }));
