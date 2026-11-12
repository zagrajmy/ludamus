import { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import { type Answer, type Door, type Ending, knock, PassKeeper } from "./bootstrap";
import { BoardCanvas } from "./canvas";
import { type Copy, FALLBACK, withFallbacks } from "./copy";
import { NameForm } from "./name-form";
import { Notice } from "./notice";

type Stage =
  | { copy: Copy; ending: Ending; kind: "ended" }
  | { copy: Copy; failed: boolean; kind: "name" }
  | { copy: Copy; kind: "failed" }
  | { keeper: PassKeeper; kind: "ready" }
  | { kind: "loading" };

type Mount = { door: Door; first: Promise<Answer>; language: string; licenseKey: string };

function Board({ door, first, language, licenseKey }: Mount) {
  const [stage, setStage] = useState<Stage>({ kind: "loading" });

  const settle = useCallback(
    (answer: Answer, previous: Copy = FALLBACK) => {
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
      } else if (answer.kind === "name-required") {
        setStage({ copy: withFallbacks(answer.copy), failed: false, kind: "name" });
      } else if (answer.kind === "gone") {
        setStage({ copy: previous, ending: "gone", kind: "ended" });
      } else {
        setStage({ copy: previous, kind: "failed" });
      }
    },
    [door],
  );

  useEffect(() => {
    void first.then((answer) => settle(answer));
  }, [first, settle]);

  switch (stage.kind) {
    case "ended":
      return stage.ending === "gone" ? (
        <Notice text={stage.copy.boardGone} />
      ) : (
        <Notice
          action={{ label: stage.copy.reload, run: () => location.reload() }}
          text={stage.copy.linkReset}
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
          text={stage.copy.bootstrapFailed}
        />
      );
    case "loading":
      return <Notice busy text={FALLBACK.loading} />;
    case "name":
      return (
        <NameForm
          copy={stage.copy}
          failed={stage.failed}
          onSubmit={async (name) => {
            const answer = await knock(door, name);
            if (answer.kind === "failed") setStage({ ...stage, failed: true });
            else settle(answer, stage.copy);
          }}
        />
      );
    case "ready":
      return <BoardCanvas keeper={stage.keeper} language={language} licenseKey={licenseKey} />;
  }
}

export function mountBoard(element: HTMLElement, mount: Mount): void {
  createRoot(element).render(<Board {...mount} />);
}
