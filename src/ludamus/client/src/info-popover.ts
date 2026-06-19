
const OPEN_DELAY_MS = 100;
const CLOSE_DELAY_MS = 200;

const init = (details: HTMLDetailsElement): void => {
  let openTimer: number | undefined;
  let closeTimer: number | undefined;

  const open = (): void => {
    window.clearTimeout(closeTimer);
    openTimer = window.setTimeout(() => {
      details.open = true;
    }, OPEN_DELAY_MS);
  };
  const close = (): void => {
    window.clearTimeout(openTimer);
    closeTimer = window.setTimeout(() => {
      details.open = false;
    }, CLOSE_DELAY_MS);
  };

  details.addEventListener("mouseenter", open);
  details.addEventListener("mouseleave", close);
  details.addEventListener("toggle", () => {
    window.clearTimeout(openTimer);
    window.clearTimeout(closeTimer);
  });
};

const wire = (): void => {
  document
    .querySelectorAll<HTMLDetailsElement>("details[data-info-popover]")
    .forEach(init);
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", wire);
} else {
  wire();
}
