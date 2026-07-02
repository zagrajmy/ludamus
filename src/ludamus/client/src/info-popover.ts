const OPEN_DELAY_MS = 100;
const CLOSE_DELAY_MS = 200;

const init = (details: HTMLDetailsElement): void => {
  let openTimer: number | undefined;
  let closeTimer: number | undefined;

  const open = (): void => {
    globalThis.clearTimeout(closeTimer);
    openTimer = globalThis.setTimeout(() => {
      details.open = true;
    }, OPEN_DELAY_MS);
  };
  const close = (): void => {
    globalThis.clearTimeout(openTimer);
    closeTimer = globalThis.setTimeout(() => {
      details.open = false;
    }, CLOSE_DELAY_MS);
  };

  details.addEventListener("mouseenter", open);
  details.addEventListener("mouseleave", close);
  details.addEventListener("toggle", () => {
    globalThis.clearTimeout(openTimer);
    globalThis.clearTimeout(closeTimer);
  });
};

const wire = (): void => {
  for (const details of document.querySelectorAll<HTMLDetailsElement>(
    "details[data-info-popover]",
  )) {
    init(details);
  }
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", wire);
} else {
  wire();
}
