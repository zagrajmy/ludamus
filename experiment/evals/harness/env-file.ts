import { readFileSync } from "node:fs";

const unquote = (value: string) => {
  const trimmed = value.trim();

  const quoted =
    trimmed.length >= 2 &&
    (trimmed.startsWith('"') || trimmed.startsWith("'")) &&
    trimmed.endsWith(trimmed.charAt(0));

  return quoted ? trimmed.slice(1, -1) : trimmed;
};

export const readEnvFile = (file: string): ReadonlyMap<string, string> =>
  new Map(
    readFileSync(file, "utf-8")
      .split("\n")
      .map((line) => line.trim())
      .filter(
        (line) => line !== "" && !line.startsWith("#") && line.includes("=")
      )
      .map((line) => {
        const separator = line.indexOf("=");

        return [
          line.slice(0, separator).trim(),
          unquote(line.slice(separator + 1)),
        ] as const;
      })
  );
