// Copy-to-clipboard for any `[data-copy]` control. One delegated listener keeps
// the behavior in a single place, so every copy button — the tessera_copy chip,
// share links, "copy details" — stays declarative markup and behaves the same.
//
// On success a `[data-copy-popover]` child confirms the copy without resizing
// the button (it's absolute + pointer-events-none). The popover is an aria-live
// region: writing its label on success announces it to screen readers, clearing
// it on hide stops it re-announcing. An unavailable clipboard (insecure context)
// or a rejected write shows nothing rather than a false confirmation.

const FEEDBACK_MS = 1500;
const timers = new WeakMap<HTMLElement, number>();

const confirmCopy = (button: HTMLElement): void => {
  const popover = button.querySelector<HTMLElement>("[data-copy-popover]");
  if (!popover) return;
  popover.textContent = button.dataset.copiedLabel ?? "";
  popover.dataset.show = "";
  const pending = timers.get(button);
  if (pending !== undefined) globalThis.clearTimeout(pending);
  timers.set(
    button,
    globalThis.setTimeout(() => {
      delete popover.dataset.show;
      popover.textContent = "";
      timers.delete(button);
    }, FEEDBACK_MS),
  );
};

document.addEventListener("click", (e) => {
  const button = (e.target as Element | null)?.closest<HTMLElement>("[data-copy]");
  if (!button) return;
  let text = button.dataset.copy;
  if (text == null) return;
  // Share paths are stored origin-relative so the markup stays host-agnostic.
  if (button.dataset.copyOrigin !== undefined) text = globalThis.location.origin + text;

  const written = navigator.clipboard?.writeText(text);
  if (written) {
    written
      .then(() => confirmCopy(button))
      .catch((error: unknown) => {
        console.error("Copy failed:", error);
      });
  } else {
    // Insecure context (plain-HTTP deploy): no popover — but leave a trace.
    console.error("Clipboard API unavailable");
  }
});
