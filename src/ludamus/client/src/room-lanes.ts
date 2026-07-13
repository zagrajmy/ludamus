for (const scroller of document.querySelectorAll<HTMLElement>("[data-room-lanes-scroll]")) {
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
