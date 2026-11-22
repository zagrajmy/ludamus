import { knock } from "./bootstrap";
import { type Copy, withFallbacks } from "./copy";

// NOTE: the board page renders this root and loads this script only there.
const root = document.querySelector<HTMLElement>("[data-board-root]")!;
const {
  bootstrapUrl = "",
  csrfToken = "",
  exitLabel = "",
  exitUrl = "/",
  language = "en",
  licenseKey = "",
} = root.dataset;
const door = { bootstrapUrl, csrfToken };

// The bootstrap request and tldraw's download run side by side: on a phone
// the canvas then opens one round trip sooner.
const first = knock(door);
const { mountBoard } = await import("./board");
// NOTE: the page carries the same copy the bootstrap does, so the screens
// before it answers (loading, a failure) speak the page's language too.
const pageCopy = document.querySelector("#board-copy")?.textContent;
const copy = withFallbacks(pageCopy ? (JSON.parse(pageCopy) as Partial<Copy>) : undefined);
mountBoard(root, {
  copy,
  door,
  exit: { href: exitUrl, label: exitLabel },
  first,
  language,
  licenseKey,
});
