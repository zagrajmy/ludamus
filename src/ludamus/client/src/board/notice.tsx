import { useEffect, useRef } from "react";

// The whole screen for a board that cannot be shown: loading, gone, a reset
// link, or a failure. One sentence and at most one way forward.
export function Notice({
  action,
  busy = false,
  text,
}: {
  action?: { label: string; run: () => void };
  busy?: boolean;
  text: string;
}) {
  const message = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (!busy) message.current?.focus();
  }, [busy, text]);
  return (
    <div className="fixed inset-0 z-80 grid place-items-center bg-background px-6 pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]">
      <div className="flex max-w-sm flex-col items-center gap-5 text-center">
        <p
          aria-busy={busy}
          className="text-lg text-foreground outline-none"
          ref={message}
          role={busy ? "status" : "alert"}
          tabIndex={-1}
        >
          {text}
        </p>
        {action !== undefined && (
          <button className="btn btn-primary min-h-11" onClick={action.run} type="button">
            {action.label}
          </button>
        )}
      </div>
    </div>
  );
}
