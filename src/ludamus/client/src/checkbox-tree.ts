const descendants = (button: HTMLButtonElement): HTMLInputElement[] => {
  const row = button.closest("li");
  const list = row?.querySelector(":scope > ul");
  return list ? [...list.querySelectorAll<HTMLInputElement>("input[type=checkbox]")] : [];
};

const syncLabel = (button: HTMLButtonElement): void => {
  const boxes = descendants(button);
  const allChecked = boxes.length > 0 && boxes.every((box) => box.checked);
  button.textContent = allChecked
    ? (button.dataset.clearLabel ?? "none")
    : (button.dataset.selectLabel ?? "all");
};

for (const tree of document.querySelectorAll<HTMLElement>("[data-checkbox-tree]")) {
  const buttons = [...tree.querySelectorAll<HTMLButtonElement>("[data-checkbox-tree-branch]")];
  const syncAll = (): void => {
    for (const button of buttons) syncLabel(button);
  };
  for (const button of buttons) {
    button.addEventListener("click", () => {
      const boxes = descendants(button);
      const select = !boxes.every((box) => box.checked);
      for (const box of boxes) box.checked = select;
      syncAll();
    });
  }
  tree.addEventListener("change", syncAll);
  syncAll();
}
