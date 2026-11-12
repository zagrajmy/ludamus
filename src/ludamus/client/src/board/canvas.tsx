import { getAssetUrlsByImport } from "@tldraw/assets/imports.vite";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { type Editor, EmbedShapeUtil, Tldraw, useEditor, useToasts } from "tldraw";
import "./board.css";

import { guardExternalContent } from "./assets";
import type { PassKeeper } from "./bootstrap";
import { components } from "./chrome";
import { type Copy, withFallbacks } from "./copy";
import { DiceSheet, rollSentence } from "./dice";
import { Icon } from "./icons";
import { Notice } from "./notice";
import { PeopleSheet } from "./people";
import { PlacesSheet } from "./places-sheet";
import { useRolls } from "./rolls";
import { colorFor, isLinkReset, useBoardStore } from "./sync";
import { type BoardUi, BoardUiContext, type Panel } from "./ui";

// NOTE: fonts, icons and tldraw's own translations ship in our build: the
// Content-Security-Policy allows no host but ours.
const assetUrls = getAssetUrlsByImport();

// The 3D dice will replace the stage; it loads once the canvas is up.
const DiceStage = lazy(async () => {
  const { DiceStage: Stage } = await import("./dice-stage");
  return { default: Stage };
});

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
  keeper,
  language,
  licenseKey,
}: {
  keeper: PassKeeper;
  language: string;
  licenseKey: string;
}) {
  const { person, socketUrl } = keeper.bootstrap;
  const copy = useMemo(() => withFallbacks(keeper.bootstrap.copy), [keeper]);
  const board = socketUrl.split("/").at(-1) ?? socketUrl;
  const color = colorFor(person.id);
  const rolls = useRolls(keeper);
  const { full, store } = useBoardStore({ color, keeper, rolls });

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
    [board, color, copy, editor, language, naming, panel, person, pool, rolls],
  );

  // NOTE: tldraw logs the reason of any sync error itself.
  if (store.status === "error" && !isLinkReset(store.error)) {
    return (
      <Notice
        action={{ label: copy.reload, run: () => location.reload() }}
        text={copy.bootstrapFailed}
      />
    );
  }
  const offline = store.status === "synced-remote" && store.connectionStatus === "offline";

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
        {full && (
          <div className="fixed inset-0 z-70 grid place-items-center bg-background/90 p-6">
            <p
              className="flex max-w-sm items-center gap-3 text-center text-base text-foreground"
              role="status"
            >
              <Icon className="size-6 shrink-0 text-foreground-muted" name="Group" />
              {copy.boardFull}
            </p>
          </div>
        )}
      </div>
    </BoardUiContext.Provider>
  );
}

// NOTE: one page per board (see chrome.tsx).
const OPTIONS = { maxPages: 1 };

// A pasted YouTube or Figma link would become a frame onto that site, which
// the Content-Security-Policy refuses; it stays a plain link instead.
const SHAPE_UTILS = [EmbedShapeUtil.configure({ embedDefinitions: [] })];
