import { pushFlash } from "./flash";

const wireLogoBuilder = (): void => {
  const builder = document.querySelector<HTMLElement>("[data-logo-builder]");
  const lockup = builder?.querySelector<SVGElement>(".logo-lockup");
  const coral = builder?.querySelector<HTMLInputElement>("#lb-coral");
  if (!lockup || !coral) return;

  const sync = () => lockup.classList.toggle("mono", !coral.checked);
  coral.addEventListener("change", sync);
  sync();
};

const wire = (): void => {
  wireLogoBuilder();

  const demo = document.querySelector<HTMLElement>("[data-flash-demo]");
  if (!demo) return;

  for (const button of demo.querySelectorAll<HTMLButtonElement>("[data-flash-demo-show]")) {
    button.addEventListener("click", () => {
      const message = button.dataset.flashDemoMessage;
      const kind = button.dataset.flashDemoShow;
      if (!message || (kind !== "error" && kind !== "success")) return;
      pushFlash(kind, message);
    });
  }

  demo
    .querySelector<HTMLButtonElement>("[data-flash-demo-clear]")
    ?.addEventListener("click", () => {
      for (const flash of document.querySelectorAll<HTMLElement>(".flash-region [data-flash]")) {
        flash.querySelector<HTMLButtonElement>("[data-flash-dismiss]")?.click();
      }
    });
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", wire);
} else {
  wire();
}
