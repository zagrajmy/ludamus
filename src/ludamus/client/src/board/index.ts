import { knock } from "./bootstrap";

// NOTE: the board page renders this root and loads this script only there.
const root = document.querySelector<HTMLElement>("[data-board-root]")!;
const { bootstrapUrl = "", csrfToken = "", language = "en", licenseKey = "" } = root.dataset;
const door = { bootstrapUrl, csrfToken };

// The bootstrap request and tldraw's download run side by side: on a phone
// the canvas then opens one round trip sooner.
const first = knock(door);
const { mountBoard } = await import("./board");
mountBoard(root, { door, first, language, licenseKey });
