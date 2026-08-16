// The rooms grid lives inside the schedule region the view tabs swap
// (hx-boost), so every lookup below re-runs against the new markup and the
// previous grid's resize listener goes with it. The flag rides each scroller,
// so the page's other htmx traffic — a session modal loading — is a no-op.
let laneListeners = new AbortController();

const initRoomLanes = (): void => {
  const scrollers = [...document.querySelectorAll<HTMLElement>("[data-room-lanes-scroll]")].filter(
    (scroller) => !("lanesBound" in scroller.dataset),
  );
  if (scrollers.length === 0) return;

  laneListeners.abort();
  laneListeners = new AbortController();
  const { signal } = laneListeners;

  const measureScrollbars = (): void => {
    for (const scroller of scrollers) {
      const reserved = scroller.offsetHeight - scroller.clientHeight;
      scroller.style.setProperty("--room-lanes-sb", `${Math.max(reserved, 14)}px`);
    }
  };
  measureScrollbars();
  globalThis.addEventListener("resize", measureScrollbars, { signal });

  for (const scroller of scrollers) {
    scroller.dataset.lanesBound = "";
    const head = scroller.parentElement?.querySelector<HTMLElement>("[data-room-lanes-head]");
    if (!head) continue;
    scroller.addEventListener(
      "scroll",
      () => {
        head.scrollLeft = scroller.scrollLeft;
      },
      { passive: true, signal },
    );
  }
};

initRoomLanes();
document.body.addEventListener("htmx:afterSwap", initRoomLanes);
