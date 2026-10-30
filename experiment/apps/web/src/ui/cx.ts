export const cx = (...parts: readonly (string | false | null | undefined)[]) =>
  parts
    .filter((part): part is string => typeof part === "string" && part !== "")
    .join(" ");
