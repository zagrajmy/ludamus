import { Predicate } from "effect";

export const cx = (...parts: readonly (string | false | null | undefined)[]) =>
  parts
    .filter((part): part is string => Predicate.isString(part) && part !== "")
    .join(" ");
