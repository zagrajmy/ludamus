import { Context } from "effect";
import type { Effect } from "effect";

import type { StoreError } from "./store-error.js";

export class MediaStore extends Context.Service<
  MediaStore,
  {
    readonly save: (options: {
      readonly bytes: Uint8Array;
      readonly folder: string;
      readonly suffix: string;
    }) => Effect.Effect<string, StoreError>;
  }
>()("@zagrajmy/core/MediaStore") {}
