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
    ...document.querySelectorAll<HTMLInputElement>(
      "[data-konwencik-track-row] input[type='color']",
    ),
  ];
  // Native color inputs coerce empty values to black; untouched defaults must stay unset.
  const unsetColors = new Set(trackInputs.filter((input) => !input.getAttribute("value")));

  const update = (): void => {
    for (const cell of preview.querySelectorAll<HTMLElement>("[data-konwencik-cell]")) {
      const categoryIndex = Number(cell.dataset.categoryIndex);
      const trackIndex = Number(cell.dataset.trackIndex);
      const icon = categoryInputs[categoryIndex]?.value.trim() ?? "";
      const colorInput = trackInputs[trackIndex];
      const color = unsetColors.has(colorInput) ? "" : (colorInput?.value.trim() ?? "");
      const iconLabel = cell.querySelector<HTMLElement>("[data-konwencik-cell-icon]");

      const name = icon.startsWith("fa.")
        ? icon.slice(3).replaceAll(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)
        : "";
      const style = Object.hasOwn(__KONWENCIK_ICON_STYLES__, name)
        ? __KONWENCIK_ICON_STYLES__[name]
        : undefined;
      if (iconLabel) {
        iconLabel.className = style ? `fa-${style} fa-${name}` : "";
        const status = cell.parentElement?.querySelector<HTMLElement>(
          "[data-konwencik-icon-status]",
        );
        if (status)
          status.textContent = icon
            ? style
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
  form?.addEventListener("input", (event) => {
    if (event.target instanceof HTMLInputElement) unsetColors.delete(event.target);
    update();
  });
  form?.addEventListener("formdata", (event) => {
    for (const input of unsetColors) event.formData.set(input.name, "");
  });
  update();
}
