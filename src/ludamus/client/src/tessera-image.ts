// A tessera image carries its placeholder as its own CSS background, so the
// page is already complete with scripting off: the real `src` is in the markup,
// the browser paints the decoded image over the placeholder, and nothing here
// is needed to *see* a picture. There is no <noscript> fallback because there
// is nothing to fall back to — the markup is the fallback.
//
// What this adds is the part CSS cannot observe: whether the bytes arrived.
//
//   (no attribute)       the plate, still. What a no-JS visitor gets.
//   data-state=loading   the plate, breathing.
//   data-state=loaded    everything behind the image dropped, so a transparent
//                        PNG is not sitting on a grey plate and the preview
//                        stops costing memory.
//   data-state=error     placeholder dropped — a blur of an image that never
//                        arrived is a lie — and the plate left as the box's floor.
//
// The plate is a class and the placeholder is an inline style, so each is
// cleared where it was set: an inline declaration outranks every utility, which
// is why dropping the placeholder cannot be left to a `data-state` variant.

const MARKED = "img[data-tessera-image]";

// A cover that 404s has nothing to say, so the browser's broken-image glyph is
// pure noise sitting in the middle of a card. A transparent pixel keeps the
// reserved box and lets the plate stand in. An image with alt text does have
// something to say, so that text stays as the fallback it was written to be.
const BLANK_PIXEL =
  "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

const settle = (image: HTMLImageElement, state: "error" | "loaded"): void => {
  image.dataset.state = state;
  image.style.backgroundImage = "";
  image.style.backgroundColor = "";
  if (state === "loaded") return;

  // The plate makes this look intentional to the reader, so the console is the
  // only trace that a cover stopped being served.
  console.warn("Image failed to load, falling back to its plate:", image.src);
  if (image.alt === "") image.src = BLANK_PIXEL;
};

const isMarked = (target: EventTarget | null): target is HTMLImageElement =>
  target instanceof HTMLImageElement && target.dataset.tesseraImage !== undefined;

// One pair of capture-phase listeners covers every image on the page: `load`
// and `error` don't bubble, but capture still reaches them on the way down, and
// this way images htmx swaps in later need no re-wiring.
document.addEventListener(
  "load",
  ({ target }) => {
    // The blank pixel above loads successfully; that success is not the cover's.
    if (isMarked(target) && target.dataset.state !== "error") settle(target, "loaded");
  },
  true,
);

document.addEventListener(
  "error",
  ({ target }) => {
    if (isMarked(target)) settle(target, "error");
  },
  true,
);

// An image the browser already finished with — from cache, or decoded before
// this module ran — fired its event before anyone was listening. After the fact
// the two outcomes look like this: complete with intrinsic size, or without.
const sweep = (root: ParentNode): void => {
  for (const image of root.querySelectorAll<HTMLImageElement>(MARKED)) {
    if (image.dataset.state !== undefined) continue;
    if (image.complete) {
      settle(image, image.naturalWidth > 0 ? "loaded" : "error");
    } else {
      // Not "a request is in flight": a lazy image far below the fold has not
      // asked for anything yet. It means no bytes, which is what the plate is
      // there to cover.
      image.dataset.state = "loading";
    }
  }
};

sweep(document);

document.body.addEventListener("htmx:afterSwap", (event) => {
  const { target } = event as CustomEvent;
  sweep(target instanceof Element ? target : document);
});
