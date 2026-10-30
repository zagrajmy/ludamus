export const cx = (
  ...parts: ReadonlyArray<string | false | null | undefined>
) =>
  parts
    .filter((part): part is string => typeof part === "string" && part !== "")
    .join(" ");
