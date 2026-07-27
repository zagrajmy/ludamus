const isSameOriginBlobUrl = (url: string): boolean => url.startsWith("blob:");

const formatBytes = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const initDropzone = (label: HTMLLabelElement): void => {
  if (label.dataset.dropzoneReady === "1") return;
  label.dataset.dropzoneReady = "1";
  const input = label.querySelector<HTMLInputElement>("[data-dropzone-input]");
  const nameEls = label.querySelectorAll<HTMLElement>("[data-dropzone-name]");
  const sizeEls = label.querySelectorAll<HTMLElement>("[data-dropzone-size]");
  const preview = label.querySelector<HTMLImageElement>("[data-dropzone-preview]");
  const clearBtns = label.querySelectorAll<HTMLButtonElement>("[data-dropzone-clear]");
  const clearFlag = label.querySelector<HTMLInputElement>("[data-dropzone-clear-flag]");
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
    if (clearFlag) clearFlag.checked = false;
    for (const el of nameEls) {
      el.textContent = file.name;
    }
    for (const el of sizeEls) {
      el.textContent = formatBytes(file.size);
    }
    const accepted = new Set(input.accept.split(",").map((t) => t.trim()));
    const isImage = accepted.has(file.type) || accepted.has("image/*");
    if (preview && isImage) {
      revokePreview();
      const objectUrl = URL.createObjectURL(file);
      if (!isSameOriginBlobUrl(objectUrl)) {
        URL.revokeObjectURL(objectUrl);
        return;
      }
      previewUrl = objectUrl;
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
      if (clearFlag) clearFlag.checked = true;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }
};

const initDropzones = (root: ParentNode = document): void => {
  for (const label of root.querySelectorAll<HTMLLabelElement>("[data-dropzone]")) {
    initDropzone(label);
  }
};

initDropzones();

document.body.addEventListener("htmx:afterSwap", (event) => {
  const { target } = event as CustomEvent;
  initDropzones(target instanceof Element ? target : document);
});
