import { TLRemoteSyncError, TLSyncErrorCloseEventReason, useSync } from "@tldraw/sync";
import { useEffect, useMemo, useRef, useState } from "react";
import { atom, createUserId, type TLUserStore, UserRecordType } from "tldraw";

import { assetStore } from "./assets";
import type { PassKeeper } from "./bootstrap";
import type { Rolls } from "./rolls";

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

// The Worker closes a socket as forbidden when its link has been reset.
export const isLinkReset = (error: Error) =>
  error instanceof TLRemoteSyncError && error.reason === TLSyncErrorCloseEventReason.FORBIDDEN;

// The board's tldraw store, synced through the Worker, and whether the
// Worker turned the socket away because the board is full.
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
  const [full, setFull] = useState(false);
  const attempts = useRef({ count: 0, loaded: false, probed: false });

  // NOTE: useSync reconnects whenever this object changes, so it is built
  // once per board; a new object on each render loops React.
  const syncOptions = useMemo(() => {
    const users: TLUserStore = {
      currentUser: atom(
        "board person",
        UserRecordType.create({ color, id: createUserId(person.id), name: person.name }),
      ),
    };
    // A socket the Worker refuses (board full, or an old link) only fails
    // to open; the reason never reaches the page. One refused attempt, and
    // the roll log, which checks the pass the same way, tells which it was.
    const probe = async () => {
      const response = await fetch(`${keeper.bootstrap.httpUrl}/rolls`, {
        headers: { Authorization: `Bearer ${await keeper.pass()}` },
      }).catch(() => null);
      if (response?.status === 403) keeper.end("link-reset");
      else if (response?.ok === true && !attempts.current.loaded) setFull(true);
    };
    return {
      assets: assetStore,
      onCustomMessageReceived: rolls.receive,
      uri: async () => {
        const state = attempts.current;
        state.count += 1;
        if (state.count > 1 && !state.loaded && !state.probed) {
          state.probed = true;
          void probe();
        }
        return keeper.socketUri();
      },
      users,
    };
  }, [color, keeper, person, rolls.receive]);
  const store = useSync(syncOptions);

  useEffect(() => {
    if (store.status === "synced-remote") {
      attempts.current.loaded = true;
      setFull(false);
    }
    if (store.status === "error" && isLinkReset(store.error)) keeper.end("link-reset");
  }, [keeper, store]);

  return { full, store };
}
