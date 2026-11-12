import { useEffect, useRef, useState } from "react";

import type { Copy } from "./copy";

const MAX_NAME_LENGTH = 40;

// A guest's one step before the board: the name the others will see.
export function NameForm({
  copy,
  failed,
  onSubmit,
}: {
  copy: Copy;
  failed: boolean;
  onSubmit: (name: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  // The form is the whole page for a guest, so focus waits in its field.
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => field.current?.focus(), []);
  return (
    <div className="fixed inset-0 grid place-items-center overflow-y-auto bg-background px-4 pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]">
      <form
        className="w-full max-w-sm rounded-2xl bg-bg-secondary p-5 shadow-[0_8px_32px_rgb(37_34_32/0.12)] ring-1 ring-border"
        onSubmit={async (event) => {
          event.preventDefault();
          const trimmed = name.trim();
          if (trimmed.length === 0) return;
          setBusy(true);
          await onSubmit(trimmed);
          setBusy(false);
        }}
      >
        <label className="block text-base font-semibold text-foreground" htmlFor="board-guest-name">
          {copy.yourName}
        </label>
        <p className="mt-1 text-sm text-foreground-secondary" id="board-guest-name-help">
          {copy.nameHelp}
        </p>
        <input
          aria-describedby={
            failed ? "board-guest-name-help board-guest-name-error" : "board-guest-name-help"
          }
          autoComplete="nickname"
          className="mt-3 block h-12 w-full rounded-lg border border-border bg-bg-secondary px-3 text-base text-foreground focus:border-primary focus:outline-none"
          enterKeyHint="go"
          id="board-guest-name"
          maxLength={MAX_NAME_LENGTH}
          onChange={(event) => setName(event.target.value)}
          ref={field}
          required
          value={name}
        />
        {failed && (
          <p className="mt-2 text-sm text-danger-text" id="board-guest-name-error" role="alert">
            {copy.bootstrapFailed}
          </p>
        )}
        <button
          className="btn btn-primary mt-4 min-h-12 w-full"
          disabled={busy || name.trim().length === 0}
          type="submit"
        >
          {copy.join}
        </button>
      </form>
    </div>
  );
}
