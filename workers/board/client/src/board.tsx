import { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import {
  type Answer,
  type Bootstrap,
  type Door,
  type Ending,
  knock,
  PassKeeper,
} from "./bootstrap";
import { BoardCanvas } from "./canvas";
import { type Copy, fill } from "./copy";
import { NameForm } from "./name-form";
import { Notice } from "./notice";

type Stage =
  | { ending: Ending; exit: Exit; kind: "ended" }
  | { error: string | null; kind: "name" }
  | { exit: Exit; keeper: PassKeeper; kind: "ready" }
  | { kind: "failed"; text: string }
  | { kind: "loading" };

export type Exit = { href: string; label: string };

type Mount = {
  copy: Copy;
  door: Door;
  // Where a person goes before Django has said whose board this is.
  fallbackExit: Exit;
  first: Promise<Answer>;
  language: string;
  licenseKey: string;
};

// Where a person goes from the board: "My boards" on its sphere for a
// member, the sphere itself for a guest.
function exitOf(copy: Copy, { boardsUrl, sphere }: Bootstrap): Exit {
  return boardsUrl === null
    ? { href: sphere.url, label: fill(copy.backTo, { sphere: sphere.name }) }
    : { href: boardsUrl, label: copy.myBoards };
}

function Board({ copy, door, fallbackExit, first, language, licenseKey }: Mount) {
  const [stage, setStage] = useState<Stage>({ kind: "loading" });

  const settle = useCallback(
    (answer: Answer) => {
      if (answer.kind === "ready") {
        const exit = exitOf(copy, answer.bootstrap);
        document.title = answer.bootstrap.title;
        // NOTE: an ending only ever moves forward; a late renewal answer
        // must not bring a reset board back.
        const keeper = new PassKeeper(door, answer.bootstrap, (ending) =>
          setStage((current) =>
            current.kind === "ended" ? current : { ending, exit, kind: "ended" },
          ),
        );
        setStage({ exit, keeper, kind: "ready" });
      } else if (answer.kind === "name-required" || answer.kind === "name-invalid") {
        const error = answer.kind === "name-invalid" ? copy.nameInvalid : null;
        setStage({ error, kind: "name" });
      } else if (answer.kind === "gone") {
        setStage({ ending: "gone", exit: fallbackExit, kind: "ended" });
      } else {
        const text = answer.kind === "throttled" ? copy.tooManyTries : copy.bootstrapFailed;
        setStage({ kind: "failed", text });
      }
    },
    [copy, door, fallbackExit],
  );

  useEffect(() => {
    void first.then((answer) => settle(answer));
  }, [first, settle]);

  switch (stage.kind) {
    // NOTE: a reload cannot help either ending: the old link opens nothing.
    case "ended":
      return (
        <Notice
          action={stage.exit}
          text={stage.ending === "gone" ? copy.boardGone : copy.linkReset}
        />
      );
    case "failed":
      return (
        <Notice
          action={{
            label: copy.retry,
            run: () => {
              setStage({ kind: "loading" });
              void knock(door).then(settle);
            },
          }}
          text={stage.text}
        />
      );
    case "loading":
      return <Notice busy text={copy.loading} />;
    case "name":
      return (
        <NameForm
          copy={copy}
          error={stage.error}
          onSubmit={async (name) => {
            const answer = await knock(door, name);
            if (answer.kind === "failed") setStage({ ...stage, error: copy.bootstrapFailed });
            else if (answer.kind === "throttled") {
              setStage({ ...stage, error: copy.tooManyTries });
            } else settle(answer);
          }}
        />
      );
    case "ready":
      return (
        <BoardCanvas
          copy={copy}
          exit={stage.exit}
          keeper={stage.keeper}
          language={language}
          licenseKey={licenseKey}
        />
      );
  }
}

export function mountBoard(element: HTMLElement, mount: Mount): void {
  createRoot(element).render(<Board {...mount} />);
}
