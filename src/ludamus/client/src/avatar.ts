// Avatars stack the photo on top of an initials placeholder, so an image that
// never loads only has to get out of the way — hiding it uncovers the initials
// instead of leaving the browser's broken-image glyph on the page.
//
// One capture-phase listener on the document covers every avatar: `error`
// doesn't bubble, but capture still reaches the image on the way down, and it
// catches avatars htmx swaps in later without re-wiring anything.

const hide = (image: HTMLImageElement): void => {
  image.hidden = true;
};

document.addEventListener(
  "error",
  (event) => {
    const { target } = event;
    if (target instanceof HTMLImageElement && target.dataset.avatarImage !== undefined) {
      hide(target);
    }
  },
  true,
);

// A cached failure (a 404 the browser still has) can fire before this module
// runs. After the fact a failed image looks like this: done loading, no
// intrinsic size.
const sweepLoaded = (): void => {
  for (const image of document.querySelectorAll<HTMLImageElement>("img[data-avatar-image]")) {
    if (image.complete && image.naturalWidth === 0) hide(image);
  }
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", sweepLoaded);
} else {
  sweepLoaded();
}
