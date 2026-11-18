import type { ReactNode } from "react";

import type { Bootstrap } from "./protocol";
import type { History } from "./use-room";

const TEXT_BUTTON =
  "rounded-full px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary-light focus-visible:outline-2 focus-visible:outline-border-focus";

// Stand-ins for a thread still on its way, laid out like one: others on the
// left behind a face, this person on the right.
const SKELETON = [
  { own: false, width: "w-40" },
  { own: false, width: "w-28" },
  { own: true, width: "w-36" },
  { own: false, width: "w-48" },
  { own: true, width: "w-24" },
] as const;
const BONE = "rounded-full bg-warm-200 motion-safe:animate-pulse dark:bg-neutral-800";

function ThreadSkeleton() {
  return (
    <div aria-hidden="true" className="parley-skeleton flex flex-col gap-3 px-3 pt-6">
      {SKELETON.map(({ own, width }, index) => (
        <div className={`flex items-end gap-2 ${own ? "flex-row-reverse" : ""}`} key={index}>
          {!own && <span className={`size-7 shrink-0 ${BONE}`} />}
          <span className={`h-9 ${BONE} ${width}`} />
        </div>
      ))}
    </div>
  );
}

type Copy = Bootstrap["copy"];

function HistoryFailed({ copy, retry, shown }: { copy: Copy; retry: () => void; shown: boolean }) {
  return (
    <p
      className={`${shown ? "mx-auto mt-3" : "m-auto"} flex flex-wrap items-center justify-center gap-x-1 px-6 text-center text-sm text-foreground-muted`}
      role="alert"
    >
      {copy.historyFailed}
      <button className={TEXT_BUTTON} onClick={retry} type="button">
        {copy.retry}
      </button>
    </p>
  );
}

type Edge = {
  copy: Copy;
  earlier: boolean;
  // What the room says once it has answered that it holds no messages.
  empty: ReactNode;
  loadEarlier: () => void;
  // Whether the start of the history says messages go after a year.
  retention: boolean;
  // Whether any message is on screen.
  shown: boolean;
};

function HistoryEdge({ copy, earlier, empty, loadEarlier, retention, shown }: Edge) {
  if (!shown) return empty;
  if (earlier)
    return (
      <button className={`mx-auto mt-3 ${TEXT_BUTTON}`} onClick={loadEarlier} type="button">
        {copy.loadEarlier}
      </button>
    );
  if (!retention) return null;
  return (
    <p className="mx-auto mt-3 max-w-64 px-6 text-center text-xs text-foreground-muted">
      {copy.retentionNote}
    </p>
  );
}

// What sits above the first message: the way to earlier ones, where the
// history ends, or, with nothing to show yet, why.
export function ThreadStart({ history, ...edge }: Edge & { history: History }) {
  if (history.state === "failed")
    return <HistoryFailed copy={edge.copy} retry={history.retry} shown={edge.shown} />;
  if (history.state === "ready") return <HistoryEdge {...edge} />;
  return edge.shown ? null : <ThreadSkeleton />;
}
