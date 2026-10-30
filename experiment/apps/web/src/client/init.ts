import type { Runtime } from "foldkit";

import type { Flags, Model } from "./model.js";
import type { Message } from "./message.js";

export const init: Runtime.RoutingApplicationInit<Model, Message, Flags> = (
  flags
) => ({ model: { ...flags, menuOpen: false } });
