const start = document.getElementById(
  "id_start_time",
) as HTMLInputElement | null;
const end = document.getElementById("id_end_time") as HTMLInputElement | null;

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
  // Idempotent: a label may be re-scanned after an HTMX swap.
  if (label.dataset.dropzoneReady === "1") return;
  label.dataset.dropzoneReady = "1";
  const input = label.querySelector<HTMLInputElement>("[data-dropzone-input]");
  const nameEls = label.querySelectorAll<HTMLElement>("[data-dropzone-name]");
  const sizeEls = label.querySelectorAll<HTMLElement>("[data-dropzone-size]");
  const preview = label.querySelector<HTMLImageElement>(
    "[data-dropzone-preview]",
  );
  const clearBtns = label.querySelectorAll<HTMLButtonElement>(
    "[data-dropzone-clear]",
  );
  const clearFlag = label.querySelector<HTMLInputElement>(
    "[data-dropzone-clear-flag]",
  );
  if (!input || nameEls.length === 0 || sizeEls.length === 0) return;

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
    for (const el of nameEls) {
      el.textContent = file.name;
    }
    for (const el of sizeEls) {
      el.textContent = formatBytes(file.size);
    }
    // Mirror the accepted upload formats (COVER_IMAGE_ACCEPT) so an
    // about-to-be-rejected file (e.g. GIF) doesn't get a misleading preview.
    const isImage = /^image\/(png|jpe?g|webp|avif)$/.test(file.type);
    if (preview && isImage) {
      revokePreview();
      previewUrl = URL.createObjectURL(file);
      preview.src = previewUrl;
      label.dataset.state = "image";
    } else {
      revokePreview();
      if (preview) preview.removeAttribute("src");
      label.dataset.state = "file";
    }
  });

  for (const clearBtn of clearBtns) {
    clearBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      input.value = "";
      // Signal removal of the already-stored file on the next submit.
      if (clearFlag) clearFlag.checked = true;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }
};

const initDropzones = (root: ParentNode = document): void => {
  for (const label of root.querySelectorAll<HTMLLabelElement>(
    "[data-dropzone]",
  )) {
    initDropzone(label);
  }
};

initDropzones();

// The propose wizard swaps its review step (with the dropzone) in via HTMX;
// this module only evaluates once, so re-scan swapped-in content.
document.body.addEventListener("htmx:afterSwap", (event) => {
  const { target } = event as CustomEvent;
  initDropzones(target instanceof Element ? target : document);
});
