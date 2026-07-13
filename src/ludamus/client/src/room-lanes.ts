const scrollers = document.querySelectorAll<HTMLElement>("[data-room-lanes-scroll]");

const measureScrollbars = (): void => {
  for (const scroller of scrollers) {
    const reserved = scroller.offsetHeight - scroller.clientHeight;
    scroller.style.setProperty("--room-lanes-sb", `${Math.max(reserved, 14)}px`);
  }
};
measureScrollbars();
globalThis.addEventListener("resize", measureScrollbars);

for (const scroller of scrollers) {
  const head = scroller.parentElement?.querySelector<HTMLElement>("[data-room-lanes-head]");
  if (!head) continue;
  scroller.addEventListener(
    "scroll",
    () => {
      head.scrollLeft = scroller.scrollLeft;
    },
    { passive: true },
  );
}
