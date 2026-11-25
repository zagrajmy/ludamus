import { TLRemoteSyncError, TLSyncErrorCloseEventReason, useSync } from "@tldraw/sync";
import { useEffect, useMemo, useState } from "react";
import { atom, createUserId, type TLUserStore, UserRecordType } from "tldraw";

import type { PassKeeper } from "./bootstrap";
import type { Rolls } from "./rolls";

import { assetStore } from "./assets";

// tldraw's cursor colours, picked by person so a colour stays with them.
const COLORS = [
  "#ff802b",
  "#ec5e41",
  "#f2555a",
  "#f04f88",
  "#e34ba9",
  "#bd54c6",
  "#9d5bd2",
  "#7b66dc",
  "#02b1cc",
  "#11b3a3",
  "#39b178",
  "#55b467",
];

export function colorFor(id: string): string {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.codePointAt(0)!) % 2_147_483_647;
  return COLORS[hash % COLORS.length]!;
}

export type Refusal = "full" | "gone" | "link-reset";

// The Worker accepts a socket it must turn away and closes it at once with
// tldraw's final close code and one of these reasons (workers/board README,
// "Refusals").
const REFUSALS: Partial<Record<string, Refusal>> = {
  [TLSyncErrorCloseEventReason.FORBIDDEN]: "link-reset",
  [TLSyncErrorCloseEventReason.NOT_FOUND]: "gone",
  [TLSyncErrorCloseEventReason.ROOM_FULL]: "full",
};

export const refusalOf = (error: Error): Refusal | null =>
  error instanceof TLRemoteSyncError ? (REFUSALS[error.reason] ?? null) : null;

// NOTE: a full board refuses for good as far as tldraw is concerned; the
// board asks again this often, so a person gets in once someone leaves.
const FULL_RETRY_MS = 15_000;

// The board's tldraw store, synced through the Worker. A reset link or a
// deleted board ends the board for this person; a full one waits.
export function useBoardStore({
  color,
  keeper,
  rolls,
}: {
  color: string;
  keeper: PassKeeper;
  rolls: Rolls;
}) {
  const { person } = keeper.bootstrap;
  const [attempt, setAttempt] = useState(0);

  // NOTE: useSync reconnects whenever this object changes, so it is built
  // once per board and attempt; a new object on each render loops React.
  const syncOptions = useMemo(() => {
    const users: TLUserStore = {
      currentUser: atom(
        "board person",
        UserRecordType.create({ color, id: createUserId(person.id), name: person.name }),
      ),
    };
    return {
      assets: assetStore,
      attempt,
      onCustomMessageReceived: rolls.receive,
      uri: async () => keeper.socketUri(),
      users,
    };
  }, [attempt, color, keeper, person, rolls.receive]);
  const store = useSync(syncOptions);
  const error = store.status === "error" ? store.error : null;
  const refusal = error === null ? null : refusalOf(error);

  // NOTE: useSync keeps the old error until the next one replaces it, so a
  // second ROOM_FULL leaves refusal at "full"; the error object is what
  // changes, and the retry re-arms on it.
  useEffect(() => {
    if (refusal === "gone" || refusal === "link-reset") keeper.end(refusal);
    if (refusal !== "full") return;
    const retry = setTimeout(() => setAttempt((count) => count + 1), FULL_RETRY_MS);
    return () => clearTimeout(retry);
  }, [error, keeper, refusal]);

  return { refusal, store };
}
