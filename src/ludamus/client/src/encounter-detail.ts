// Encounter detail page: the countdown, the organizer's QR dialog, and the
// "save the date" prompt that collapses to "Saved" once the attendee has
// copied the details or picked a calendar. The calendar and share menus are
// tessera_action_dropdown (menu.ts).

const pad = (n: number): string => (n < 10 ? `0${n}` : String(n));

const startCountdown = (): void => {
  const el = document.getElementById("encounter-countdown");
  if (!el) return;
  const startTime = new Date(el.dataset.startTime ?? "").getTime();
  const startedText = el.dataset.startedText ?? "";
  const parts = ["days", "hours", "minutes", "seconds"].map((unit) =>
    document.getElementById(`cd-${unit}`),
  );

  const update = (): void => {
    const diff = startTime - Date.now();
    if (diff <= 0) {
      el.className = "text-center text-sm text-foreground-secondary";
      el.textContent = startedText;
      return;
    }
    const values = [
      Math.floor(diff / 86_400_000),
      Math.floor((diff % 86_400_000) / 3_600_000),
      Math.floor((diff % 3_600_000) / 60_000),
      Math.floor((diff % 60_000) / 1000),
    ];
    for (const [index, part] of parts.entries()) {
      if (part) part.textContent = pad(values[index]);
    }
    requestAnimationFrame(update);
  };
  update();
};

// NOTE: opening the dialog moves focus out of the share menu, and menu.ts
// closes a menu on focusin outside it — so the menu needs no explicit close.
const wireQrDialog = (): void => {
  for (const button of document.querySelectorAll<HTMLElement>("[data-show-qr]")) {
    button.addEventListener("click", () => {
      const dialog = document.getElementById(button.dataset.showQr ?? "");
      if (dialog instanceof HTMLDialogElement) dialog.showModal();
    });
  }
  for (const dialog of document.querySelectorAll<HTMLDialogElement>("dialog[data-qr-dialog]")) {
    dialog.addEventListener("click", (event: MouseEvent) => {
      if (event.target === dialog) dialog.close();
    });
  }
};

const SAVE_COLLAPSE_DELAY_MS = 300;

const setSaved = (card: HTMLElement, saved: boolean): void => {
  card.querySelector("[data-rsvp-save-prompt]")?.classList.toggle("hidden", saved);
  card.querySelector("[data-rsvp-save-done]")?.classList.toggle("hidden", !saved);
};

const wireSavePrompt = (card: HTMLElement): void => {
  for (const button of card.querySelectorAll<HTMLElement>("[data-rsvp-restore-prompt]")) {
    button.addEventListener("click", () => setSaved(card, false));
  }
  // Copying is handled by copy.ts, which reveals the popover only on a
  // successful write and hides it again when the feedback is done. Collapse
  // the save prompt at that hide — so never on a failed copy, and without
  // duplicating copy.ts's timing here. One observer per popover, attached up
  // front like the other prompt wiring, so repeated clicks can't stack
  // observers (#476). data-show only ever mutates on success, and its removal
  // marks the feedback's end.
  for (const popover of card.querySelectorAll<HTMLElement>(
    "[data-rsvp-save-prompt] [data-copy] [data-copy-popover]",
  )) {
    new MutationObserver(() => {
      if (popover.dataset.show === undefined) setSaved(card, true);
    }).observe(popover, { attributeFilter: ["data-show"], attributes: true });
  }
  for (const link of card.querySelectorAll<HTMLAnchorElement>("[data-rsvp-save-prompt] a[href]")) {
    link.addEventListener("click", () => {
      globalThis.setTimeout(() => setSaved(card, true), SAVE_COLLAPSE_DELAY_MS);
    });
  }
};

startCountdown();
wireQrDialog();
for (const card of document.querySelectorAll<HTMLElement>("[data-rsvp-save]")) {
  wireSavePrompt(card);
}
