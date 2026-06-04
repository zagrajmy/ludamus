const start = document.getElementById(
  "id_start_time",
) as HTMLInputElement | null;
const end = document.getElementById(
  "id_end_time",
) as HTMLInputElement | null;

const DEFAULT_DURATION_HOURS = 3;

const pad = (n: number): string => String(n).padStart(2, "0");

const toLocalDatetimeValue = (d: Date): string =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
  `T${pad(d.getHours())}:${pad(d.getMinutes())}`;

if (start && end) {
  start.addEventListener("change", () => {
    if (end.value || !start.value) return;
    const d = new Date(start.value);
    if (Number.isNaN(d.getTime())) return;
    d.setHours(d.getHours() + DEFAULT_DURATION_HOURS);
    end.value = toLocalDatetimeValue(d);
  });
}

const formatBytes = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const initDropzone = (label: HTMLLabelElement): void => {
  const input = label.querySelector<HTMLInputElement>("[data-dropzone-input]");
  const nameEls = label.querySelectorAll<HTMLElement>("[data-dropzone-name]");
  const sizeEls = label.querySelectorAll<HTMLElement>("[data-dropzone-size]");
  const preview = label.querySelector<HTMLImageElement>(
    "[data-dropzone-preview]",
  );
  const clearBtns =
    label.querySelectorAll<HTMLButtonElement>("[data-dropzone-clear]");
  const clearFlag = label.querySelector<HTMLInputElement>(
    "[data-dropzone-clear-flag]",
  );
  if (!input || nameEls.length === 0 || sizeEls.length === 0) return;
  if (clearBtns.length === 0) return;

  let previewUrl: string | null = null;
  const revokePreview = (): void => {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = null;
    }
  };

  input.addEventListener("change", () => {
    const file = input.files?.[0];
    if (!file) {
      revokePreview();
      if (preview) preview.removeAttribute("src");
      label.dataset.state = "empty";
      return;
    }
    // A fresh selection cancels any pending removal of the stored file.
    if (clearFlag) clearFlag.checked = false;
    nameEls.forEach((el) => {
      el.textContent = file.name;
    });
    sizeEls.forEach((el) => {
      el.textContent = formatBytes(file.size);
    });
    const useImageLayout =
      Boolean(preview) &&
      /^image\/(png|jpe?g|gif|webp|avif)$/.test(file.type);
    if (useImageLayout) {
      revokePreview();
      previewUrl = URL.createObjectURL(file);
      preview!.src = previewUrl;
      label.dataset.state = "image";
    } else {
      revokePreview();
      if (preview) preview.removeAttribute("src");
      label.dataset.state = "file";
    }
  });

  clearBtns.forEach((clearBtn) => {
    clearBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      input.value = "";
      // Signal removal of the already-stored file on the next submit.
      if (clearFlag) clearFlag.checked = true;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
};

document
  .querySelectorAll<HTMLLabelElement>("[data-dropzone]")
  .forEach(initDropzone);
