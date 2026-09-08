import "@fortawesome/fontawesome-free/css/all.css";

declare const __KONWENCIK_ICON_STYLES__: Record<string, string>;

const preview = document.querySelector<HTMLElement>("[data-konwencik-preview]");

const validColor = /^#[0-9a-f]{6}$/i;

const readableForeground = (color: string): string => {
  const channels = [1, 3, 5].map((start) => {
    const channel = Number.parseInt(color.slice(start, start + 2), 16) / 255;
    return channel <= 0.040_45 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  const luminance = channels.reduce(
    (sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index],
    0,
  );
  return luminance > 0.2 ? "#171717" : "#ffffff";
};

if (preview) {
  const categoryInputs = [
    ...document.querySelectorAll<HTMLInputElement>(
      "[data-konwencik-category-row] input[type='text']",
    ),
  ];
  const trackInputs = [
    ...document.querySelectorAll<HTMLInputElement>("[data-konwencik-track-row] input[type='text']"),
  ];

  const update = (): void => {
    for (const cell of preview.querySelectorAll<HTMLElement>("[data-konwencik-cell]")) {
      const categoryIndex = Number(cell.dataset.categoryIndex);
      const trackIndex = Number(cell.dataset.trackIndex);
      const icon = categoryInputs[categoryIndex]?.value.trim() ?? "";
      const color = trackInputs[trackIndex]?.value.trim() ?? "";
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
      cell.style.color = validColor.test(color) ? readableForeground(color) : "";
    }
  };

  document
    .querySelector<HTMLFormElement>("#konwencik-settings-form")
    ?.addEventListener("input", update);
  update();
}
