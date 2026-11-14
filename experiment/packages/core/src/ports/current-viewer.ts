import { Context, Schema } from "effect";
import type { Option } from "effect";

import { UserId } from "../ids.js";

export const Viewer = Schema.Struct({
  id: UserId,
  isSuperuser: Schema.Boolean,
});

export type Viewer = typeof Viewer.Type;

export class CurrentViewer extends Context.Service<
  CurrentViewer,
  Option.Option<Viewer>
>()("@zagrajmy/core/CurrentViewer") {}
