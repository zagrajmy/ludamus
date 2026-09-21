const validColor = /^#[0-9a-f]{6}$/i;

for (const field of document.querySelectorAll<HTMLElement>("[data-color-field]")) {
  const text = field.querySelector<HTMLInputElement>('input[type="text"]');
  const picker = field.querySelector<HTMLInputElement>('input[type="color"]');
  if (!text || !picker) continue;

  const syncPicker = (): void => {
    const value = text.value.trim();
    picker.value = validColor.test(value) ? value : "#000000";
    picker.style.opacity = validColor.test(value) ? "" : "0.5";
  };
  picker.hidden = false;
  syncPicker();
  text.addEventListener("input", syncPicker);
  picker.addEventListener("input", () => {
    text.value = picker.value;
    text.dispatchEvent(new Event("input", { bubbles: true }));
  });
  text.form?.addEventListener("reset", () => queueMicrotask(syncPicker));
}
