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

      if (iconLabel) iconLabel.textContent = icon || "—";
      cell.style.backgroundColor = validColor.test(color) ? color : "";
      cell.style.color = validColor.test(color) ? readableForeground(color) : "";
    }

    for (const swatch of preview.querySelectorAll<HTMLElement>("[data-konwencik-swatch]")) {
      const index = Number(swatch.dataset.konwencikSwatch);
      const color = trackInputs[index]?.value.trim() ?? "";
      swatch.style.backgroundColor = validColor.test(color) ? color : "";
    }
  };

  document
    .querySelector<HTMLFormElement>("#konwencik-settings-form")
    ?.addEventListener("input", update);
  update();
}
