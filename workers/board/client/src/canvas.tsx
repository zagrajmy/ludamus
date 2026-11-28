import { getAssetUrlsByImport } from "@tldraw/assets/imports.vite";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { type Editor, EmbedShapeUtil, Tldraw, useEditor, useToasts } from "tldraw";

import "./board.css";

import type { Exit } from "./board";
import type { PassKeeper } from "./bootstrap";
import type { Copy } from "./copy";

import { guardExternalContent } from "./assets";
import { components } from "./chrome";
import { DiceSheet, rollSentence } from "./dice";
import { Notice } from "./notice";
import { PeopleSheet } from "./people";
import { PlacesSheet } from "./places-sheet";
import { useRolls } from "./rolls";
import { colorFor, useBoardStore } from "./sync";
import { type BoardUi, BoardUiContext, type Panel } from "./ui";

// NOTE: fonts, icons and tldraw's own translations ship in our build: the
// Content-Security-Policy allows no host but ours.
const assetUrls = getAssetUrlsByImport();

// The dice load after the canvas is usable (see warmUpDice).
const DiceStage = lazy(async () => {
  const { DiceStage: Stage } = await import("./dice-stage");
  return { default: Stage };
});

const loadDice = () => {
  void import("./dice-stage");
  void import("./dice-3d");
};

// Fetches the dice code while the page is idle, so the first roll does not
// wait for it. Safari has no requestIdleCallback.
function warmUpDice(): () => void {
  if ("requestIdleCallback" in globalThis) {
    const handle = requestIdleCallback(loadDice, { timeout: 5000 });
    return () => cancelIdleCallback(handle);
  }
  const handle = setTimeout(loadDice, 1500);
  return () => clearTimeout(handle);
}

function Guard({ copy }: { copy: Copy }) {
  const editor = useEditor();
  const toasts = useToasts();
  useEffect(() => {
    guardExternalContent(editor, { comingSoon: copy.imagesComingSoon, toasts });
  }, [copy, editor, toasts]);
  return null;
}

function ConnectionBanner({ copy }: { copy: Copy }) {
  return (
    <p
      className="pointer-events-none fixed inset-x-0 top-[max(0.75rem,env(safe-area-inset-top))] z-30 mx-auto w-fit max-w-[calc(100%-2rem)] rounded-full bg-warm-900 px-4 py-2 text-center text-sm text-white shadow-lg"
      role="status"
    >
      {copy.connectionLost}
    </p>
  );
}

export function BoardCanvas({
  copy,
  exit,
  keeper,
  language,
  licenseKey,
}: {
  copy: Copy;
  exit: Exit;
  keeper: PassKeeper;
  language: string;
  licenseKey: string;
}) {
  const { board, person } = keeper.bootstrap;
  const color = colorFor(person.id);
  const rolls = useRolls(keeper);
  const { refusal, store } = useBoardStore({ color, keeper, rolls });
  const usable = store.status === "synced-remote";
  useEffect(() => (usable ? warmUpDice() : undefined), [usable]);
  const online = usable && store.connectionStatus === "online";
  const { refresh } = rolls;
  useEffect(() => {
    if (online) void refresh();
  }, [online, refresh]);
  // tldraw keeps trying a Worker it cannot reach behind a bare spinner; after
  // a while the person is told why nothing shows.
  const [stalled, setStalled] = useState(false);
  const connecting = store.status === "loading";
  useEffect(() => {
    setStalled(false);
    if (!connecting) return;
    const timer = setTimeout(() => setStalled(true), STALLED_AFTER_MS);
    return () => clearTimeout(timer);
  }, [connecting]);

  const [editor, setEditor] = useState<Editor | null>(null);
  const [panel, setPanel] = useState<Panel | null>(null);
  const [naming, setNaming] = useState<BoardUi["naming"]>(null);
  const [pool, setPool] = useState<number[]>([]);
  const ui = useMemo<BoardUi>(
    () => ({
      board,
      color,
      copy,
      editor,
      exit,
      locale: language,
      naming,
      open: (next) => {
        setPanel(next);
        if (next !== "places") setNaming(null);
      },
      panel,
      person,
      pool,
      rolls,
      setNaming,
      setPool,
    }),
    [board, color, copy, editor, exit, language, naming, panel, person, pool, rolls],
  );

  // NOTE: a full board waits and asks again (useBoardStore); the way out
  // stays in reach meanwhile.
  if (refusal === "full") return <Notice action={exit} text={copy.boardFull} />;
  // NOTE: a reset link or a deleted board ends the board (keeper.end).
  if (refusal !== null) return <Notice busy text={copy.loading} />;
  // NOTE: tldraw logs the reason of any sync error itself.
  if (store.status === "error") {
    return (
      <Notice
        action={{ label: copy.reload, run: () => location.reload() }}
        text={copy.bootstrapFailed}
      />
    );
  }
  const offline =
    (store.status === "synced-remote" && store.connectionStatus === "offline") ||
    (connecting && stalled);

  return (
    <BoardUiContext.Provider value={ui}>
      <div className="fixed inset-0 overflow-hidden">
        {/* NOTE: isolate keeps tldraw's own layers (its UI sits at z-index 300) under the board's sheets. */}
        <div className="absolute inset-0 isolate">
          <Tldraw
            assetUrls={assetUrls}
            components={components}
            licenseKey={licenseKey === "" ? undefined : licenseKey}
            locale={language}
            onMount={setEditor}
            options={OPTIONS}
            shapeUtils={SHAPE_UTILS}
            store={store}
          >
            <Guard copy={copy} />
          </Tldraw>
        </div>
        {offline && <ConnectionBanner copy={copy} />}
        {panel === "dice" && <DiceSheet />}
        {panel === "places" && <PlacesSheet />}
        {panel === "people" && <PeopleSheet />}
        {rolls.arrived !== null && (
          <Suspense fallback={null}>
            <DiceStage copy={copy} onSettled={rolls.settle} roll={rolls.arrived} />
          </Suspense>
        )}
        <div aria-live="polite" className="sr-only">
          {rolls.arrived !== null && rollSentence(copy, rolls.arrived)}
        </div>
      </div>
    </BoardUiContext.Provider>
  );
}

const STALLED_AFTER_MS = 8000;

// NOTE: one page per board (see chrome.tsx).
const OPTIONS = { maxPages: 1 };

// A pasted YouTube or Figma link would become a frame onto that site, which
// the Content-Security-Policy refuses; it stays a plain link instead.
const SHAPE_UTILS = [EmbedShapeUtil.configure({ embedDefinitions: [] })];
