import { implement } from "@zagrajmy/capability/implement";
import { Effect, Option } from "effect";

import { toggleBookmarkContract } from "../contracts.js";
import { SessionId } from "../ids.js";
import { BookmarkStore } from "../ports/bookmark-store.js";
import { CurrentSphere } from "../ports/current-sphere.js";
import { NotFound } from "../ports/store-error.js";
import { StoreTransaction } from "../ports/transaction.js";
import { requireViewer } from "./context.js";

export const toggleBookmark = implement(
  toggleBookmarkContract,
  ({ sessionId }) =>
    Effect.gen(function* toggleBookmarkHandler() {
      const viewer = yield* requireViewer;
      const sphere = yield* CurrentSphere;
      const bookmarks = yield* BookmarkStore;
      const transaction = yield* StoreTransaction;

      const state = yield* transaction.atomic(
        bookmarks.toggle({
          sessionId: SessionId.make(sessionId),
          sphereId: sphere.id,
          userId: viewer.id,
        })
      );

      if (Option.isNone(state)) {
        return yield* new NotFound({
          entity: "Session",
          key: String(sessionId),
        });
      }

      return state.value;
    })
);
