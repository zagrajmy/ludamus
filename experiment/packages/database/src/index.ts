import { Layer } from "effect";

import { DjangoSessionStoreLive } from "./django-session-store.js";
import { EventStoreLive } from "./event-store.js";
import { SphereStoreLive } from "./sphere-store.js";
import { SqliteLive } from "./sqlite.js";
import { UserStoreLive } from "./user-store.js";

export {
  DjangoSessionRow,
  DjangoSessionStore,
  DjangoSessionStoreLive,
} from "./django-session-store.js";
export { EventStoreLive } from "./event-store.js";
export { SphereStore, SphereStoreLive } from "./sphere-store.js";
export { SqliteLive } from "./sqlite.js";
export { UserRow, UserStore, UserStoreLive } from "./user-store.js";

export const StoresLive = Layer.mergeAll(
  DjangoSessionStoreLive,
  EventStoreLive,
  SphereStoreLive,
  UserStoreLive
);

export const DatabaseLive = StoresLive.pipe(Layer.provideMerge(SqliteLive));
