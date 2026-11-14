import { Data } from "effect";

import type { PageFlags } from "../client/model.js";
import type { FlashNote } from "./flash.js";

export type Routed = Data.TaggedEnum<{
  Page: { readonly flags: PageFlags; readonly status: number };
  Redirect: {
    readonly flashes?: readonly FlashNote[];
    readonly location: string;
    readonly status: 301 | 302;
  };
}>;

export const Routed = Data.taggedEnum<Routed>();
