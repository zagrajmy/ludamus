import { initFlash } from "./flash";

const getRegion = (): HTMLElement => {
  const existing = document.querySelector<HTMLElement>(".flash-region");
  if (existing) return existing;

  const created = document.createElement("div");
  created.className = "flash-region";
  created.setAttribute("role", "region");
  created.setAttribute("aria-label", "Notifications");
  document.body.append(created);
  return created;
};

const createFlash = (kind: string, message: string): HTMLElement => {
  const flash = document.createElement("div");
  flash.className = `alert flex items-center ${kind === "error" ? "alert-danger" : "alert-success"}`;
  flash.dataset.flash = kind === "error" ? "sticky" : "transient";
  flash.setAttribute("role", kind === "error" ? "alert" : "status");
  flash.setAttribute("aria-live", kind === "error" ? "assertive" : "polite");

  const content = document.createElement("span");
  content.className = "text-sm";
  content.textContent = message;
  flash.append(content);

  const dismiss = document.createElement("button");
  dismiss.type = "button";
  dismiss.dataset.flashDismiss = "";
  dismiss.className =
    "ml-auto pl-3 shrink-0 opacity-70 hover:opacity-100 transition-opacity cursor-pointer";
  dismiss.setAttribute("aria-label", "Dismiss");
  dismiss.textContent = "×";
  flash.append(dismiss);

  return flash;
};

const wire = (): void => {
  const demo = document.querySelector<HTMLElement>("[data-flash-demo]");
  if (!demo) return;

  for (const button of demo.querySelectorAll<HTMLButtonElement>("[data-flash-demo-show]")) {
    button.addEventListener("click", () => {
      const message = button.dataset.flashDemoMessage;
      const kind = button.dataset.flashDemoShow;
      if (!message || !kind) return;

      const flash = createFlash(kind, message);
      getRegion().prepend(flash);
      initFlash(flash);
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

const logoBuilder = document.querySelector<HTMLElement>("[data-logo-builder]");
if (logoBuilder) {
  const lockup = logoBuilder.querySelector<SVGElement>(".logo-lockup");
  const coral = logoBuilder.querySelector<HTMLInputElement>("#lb-coral");
  const chunky = logoBuilder.querySelector<HTMLInputElement>("#lb-chunky");
  const sync = () => {
    lockup?.classList.toggle("mono", coral ? !coral.checked : false);
    lockup?.classList.toggle("chunky", chunky ? chunky.checked : true);
  };
  coral?.addEventListener("change", sync);
  chunky?.addEventListener("change", sync);
  sync();
}
