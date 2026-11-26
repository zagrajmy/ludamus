import "./app.css";
import { knock } from "./bootstrap";
import { COPY, type Language } from "./copy";

// NOTE: both come from the build (vite.config.ts): the app's origin, where
// Django signs passes, and tldraw's licence key, which is public by design.
declare const __APP_ORIGIN__: string;
declare const __TLDRAW_LICENSE_KEY__: string;

const LANGUAGE_KEY = "board.language";
const isLanguage = (value: string | null): value is Language => value === "en" || value === "pl";

// The language Django had when it sent the person here (?lang=), then the
// browser's, then Polish, the site's own. The query leaves the address so a
// shared link does not carry it; the tab keeps it for a reload.
function pickLanguage(): Language {
  const url = new URL(location.href);
  const asked = url.searchParams.get("lang");
  if (isLanguage(asked)) {
    url.searchParams.delete("lang");
    history.replaceState(history.state, "", url);
    try {
      sessionStorage.setItem(LANGUAGE_KEY, asked);
    } catch {
      // NOTE: storage can be off; the language then holds for this load only.
    }
    return asked;
  }
  let kept: string | null = null;
  try {
    kept = sessionStorage.getItem(LANGUAGE_KEY);
  } catch {
    kept = null;
  }
  if (isLanguage(kept)) return kept;
  for (const tag of navigator.languages) {
    const primary = tag.split("-")[0]!.toLowerCase();
    if (isLanguage(primary)) return primary;
  }
  return "pl";
}

const language = pickLanguage();
const copy = COPY[language];
document.documentElement.lang = language;
// NOTE: the site keeps a chosen theme in its own origin's storage, out of
// reach here; the board follows the device.
if (matchMedia("(prefers-color-scheme: dark)").matches) {
  document.documentElement.classList.add("dark");
}

const root = document.querySelector<HTMLElement>("[data-board-root]")!;
// The Worker serves this page only at /b/<share code>.
const shareCode = location.pathname.split("/")[2] ?? "";
const door = {
  bootstrapUrl: `${__APP_ORIGIN__}/b/${encodeURIComponent(shareCode)}/bootstrap/`,
};

// The bootstrap request and tldraw's download run side by side: on a phone
// the canvas then opens one round trip sooner.
const first = knock(door);
const { mountBoard } = await import("./board");
mountBoard(root, {
  copy,
  door,
  fallbackExit: { href: `${__APP_ORIGIN__}/`, label: copy.backToMain },
  first,
  language,
  licenseKey: __TLDRAW_LICENSE_KEY__,
});
