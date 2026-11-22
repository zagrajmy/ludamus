import { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import { type Answer, type Door, type Ending, knock, PassKeeper } from "./bootstrap";
import { BoardCanvas } from "./canvas";
import { type Copy, withFallbacks } from "./copy";
import { NameForm } from "./name-form";
import { Notice } from "./notice";

type Stage =
  | { copy: Copy; ending: Ending; kind: "ended" }
  | { copy: Copy; error: string | null; kind: "name" }
  | { copy: Copy; kind: "failed"; text: string }
  | { keeper: PassKeeper; kind: "ready" }
  | { kind: "loading" };

export type Exit = { href: string; label: string };

type Mount = {
  // The page's own copy, for the screens shown before the bootstrap answers.
  copy: Copy;
  door: Door;
  // Where a person goes from here: "My boards", or the sphere for a guest.
  exit: Exit;
  first: Promise<Answer>;
  language: string;
  licenseKey: string;
};

function Board({ copy: pageCopy, door, exit, first, language, licenseKey }: Mount) {
  const [stage, setStage] = useState<Stage>({ kind: "loading" });

  const settle = useCallback(
    (answer: Answer, previous: Copy = pageCopy) => {
      if (answer.kind === "ready") {
        const copy = withFallbacks(answer.bootstrap.copy);
        // NOTE: an ending only ever moves forward; a late renewal answer
        // must not bring a reset board back.
        const keeper = new PassKeeper(door, answer.bootstrap, (ending) =>
          setStage((current) =>
            current.kind === "ended" ? current : { copy, ending, kind: "ended" },
          ),
        );
        setStage({ keeper, kind: "ready" });
      } else if (answer.kind === "name-required" || answer.kind === "name-invalid") {
        const copy = withFallbacks(answer.copy);
        const error = answer.kind === "name-invalid" ? copy.nameInvalid : null;
        setStage({ copy, error, kind: "name" });
      } else if (answer.kind === "gone") {
        setStage({ copy: previous, ending: "gone", kind: "ended" });
      } else {
        const text = answer.kind === "throttled" ? previous.tooManyTries : previous.bootstrapFailed;
        setStage({ copy: previous, kind: "failed", text });
      }
    },
    [door, pageCopy],
  );

  useEffect(() => {
    void first.then((answer) => settle(answer));
  }, [first, settle]);

  switch (stage.kind) {
    // NOTE: a reload cannot help either ending: the old link opens nothing.
    case "ended":
      return (
        <Notice
          action={exit}
          text={stage.ending === "gone" ? stage.copy.boardGone : stage.copy.linkReset}
        />
      );
    case "failed":
      return (
        <Notice
          action={{
            label: stage.copy.retry,
            run: () => {
              setStage({ kind: "loading" });
              void knock(door).then((answer) => settle(answer, stage.copy));
            },
          }}
          text={stage.text}
        />
      );
    case "loading":
      return <Notice busy text={pageCopy.loading} />;
    case "name":
      return (
        <NameForm
          copy={stage.copy}
          error={stage.error}
          onSubmit={async (name) => {
            const answer = await knock(door, name);
            if (answer.kind === "failed") setStage({ ...stage, error: stage.copy.bootstrapFailed });
            else if (answer.kind === "throttled") {
              setStage({ ...stage, error: stage.copy.tooManyTries });
            } else settle(answer, stage.copy);
          }}
        />
      );
    case "ready":
      return (
        <BoardCanvas
          exit={exit}
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
