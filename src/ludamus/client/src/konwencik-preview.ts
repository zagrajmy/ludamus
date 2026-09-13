import "@fortawesome/fontawesome-free/css/all.css";

declare const __KONWENCIK_ICON_STYLES__: Record<string, string>;

const preview = document.querySelector<HTMLElement>("[data-konwencik-preview]");

const validColor = /^#[0-9a-f]{6}$/i;

if (preview) {
  const categoryInputs = [
    ...document.querySelectorAll<HTMLInputElement>(
      "[data-konwencik-category-row] input[type='text']",
    ),
  ];
  const trackInputs = [
    ...document.querySelectorAll<HTMLInputElement>("[data-konwencik-track-row] input[type='text']"),
  ];

  const iconClass = (icon: string): string => {
    const name = icon.startsWith("fa.")
      ? icon.slice(3).replaceAll(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)
      : "";
    const style = Object.hasOwn(__KONWENCIK_ICON_STYLES__, name)
      ? __KONWENCIK_ICON_STYLES__[name]
      : undefined;
    return style ? `fa-${style} fa-${name}` : "";
  };

  const update = (): void => {
    for (const field of preview.querySelectorAll<HTMLElement>("[data-icon-field]")) {
      const icon = field.querySelector<HTMLInputElement>("input")?.value.trim() ?? "";
      const glyph = field.querySelector<HTMLElement>("[data-icon-field-glyph]");
      const status = field.querySelector<HTMLElement>("[data-icon-field-status]");
      const className = iconClass(icon);
      if (glyph) glyph.className = className;
      if (status)
        status.textContent = className
          ? ""
          : icon
            ? (status.dataset.unsupported ?? "")
            : (status.dataset.empty ?? "");
    }
    for (const cell of preview.querySelectorAll<HTMLElement>("[data-konwencik-cell]")) {
      const categoryIndex = Number(cell.dataset.categoryIndex);
      const trackIndex = Number(cell.dataset.trackIndex);
      const icon = categoryInputs[categoryIndex]?.value.trim() ?? "";
      const colorInput = trackInputs[trackIndex];
      const color = colorInput?.value.trim() ?? "";
      const iconLabel = cell.querySelector<HTMLElement>("[data-konwencik-cell-icon]");

      const className = iconClass(icon);
      if (iconLabel) {
        iconLabel.className = className;
        const status = cell.parentElement?.querySelector<HTMLElement>(
          "[data-konwencik-icon-status]",
        );
        if (status)
          status.textContent = icon
            ? className
              ? icon
              : (status.dataset.unsupported ?? "")
            : (status.dataset.empty ?? "");
      }
      cell.style.backgroundColor = validColor.test(color) ? color : "";
      cell.style.color = "#ffffff";
      if (cell.parentElement) cell.parentElement.hidden = !validColor.test(color);
    }
  };

  const form = document.querySelector<HTMLFormElement>("#konwencik-settings-form");
  form?.addEventListener("input", update);
  form?.addEventListener("reset", () => queueMicrotask(update));
  update();
}
