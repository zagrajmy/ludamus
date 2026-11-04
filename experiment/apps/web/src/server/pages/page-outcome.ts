import { Data } from "effect";

import type { FlashNote } from "../flash.js";

export type PageOutcome<Flags> = Data.TaggedEnum<{
  Page: { readonly flags: Flags };
  Redirect: {
    readonly location: string;
    readonly flashes: readonly FlashNote[];
  };
}>;

interface PageOutcomeDefinition extends Data.TaggedEnum.WithGenerics<1> {
  readonly taggedEnum: PageOutcome<this["A"]>;
}

export const PageOutcome = Data.taggedEnum<PageOutcomeDefinition>();
