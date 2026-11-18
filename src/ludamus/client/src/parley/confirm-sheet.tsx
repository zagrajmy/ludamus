import { useEffect, useRef } from "react";

import type { Bootstrap } from "./protocol";

type Pending = { accept: string; question: string; run: () => void };

// Asks before a destructive action in place of the composer, so the thread
// stays in view and the chat keeps its own look.
export function ConfirmSheet({
  cancel,
  copy,
  pending,
}: {
  cancel: () => void;
  copy: Bootstrap["copy"];
  pending: Pending;
}) {
  const cancelButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    cancelButton.current?.focus();
  }, []);
  return (
    <div
      aria-describedby="parley-confirm-question"
      aria-label={pending.accept}
      className="border-t border-border px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        // NOTE: preventDefault keeps the panel's own Escape (close chat) out of it.
        event.preventDefault();
        cancel();
      }}
      role="alertdialog"
    >
      <p className="text-sm text-foreground" id="parley-confirm-question">
        {pending.question}
      </p>
      <div className="mt-3 flex justify-end gap-2">
        <button
          className="btn btn-secondary text-sm"
          onClick={cancel}
          ref={cancelButton}
          type="button"
        >
          {copy.cancelLabel}
        </button>
        <button className="btn btn-danger text-sm" onClick={pending.run} type="button">
          {pending.accept}
        </button>
      </div>
    </div>
  );
}
