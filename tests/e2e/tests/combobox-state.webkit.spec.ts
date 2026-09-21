import { expect, test } from "./helpers/fixtures";

for (const name of ["Fruit", "Multiple fruit"]) {
  test(`${name}: the arrow toggles without losing input focus`, async ({ page }) => {
    await page.goto("/design/");
    const input = page.getByRole("combobox", { name, exact: true });
    await expect(input).toHaveAttribute("aria-autocomplete", "list");
    const initial = await input.inputValue();
    const toggle = input.locator("..").getByRole("button", { name: "Show options", exact: true });
    const list = page.getByRole("listbox", { name, exact: true });

    await input.click();
    await expect(list).toBeVisible();
    for (const expanded of [false, true, false]) {
      await toggle.click();
      await expect(input).toHaveAttribute("aria-expanded", String(expanded));
      await expect(toggle).toHaveAttribute("aria-expanded", String(expanded));
      await expect(list).toBeVisible({ visible: expanded });
      await expect(input).toBeFocused();
      await expect(input).toHaveValue(initial);
    }

    await input.fill("no matching fruit");
    await toggle.click();
    await expect(list).toBeHidden();
    await expect(input).toHaveValue(initial);

    await toggle.click();
    await page.getByRole("link", { name: "Privacy Policy", exact: true }).focus();
    await expect(list).toBeHidden();
    await expect(input).toHaveValue(initial);
  });
}

test("disabled multi-selections remain visible but never submit", async ({ page }) => {
  await page.goto("/design/");
  const form = page.getByRole("form", { name: "Fruit with disabled options", exact: true });
  const input = form.getByRole("combobox");
  const submitted = () =>
    form.evaluate((element) => new FormData(element as HTMLFormElement).getAll("fruit"));
  await expect(input).toHaveValue("Apple, Cherry");
  expect(await submitted()).toEqual(["cherry"]);

  await input.evaluate((element) => {
    element.closest("[data-combobox]")?.dispatchEvent(new CustomEvent("combobox:sync"));
  });
  await expect(input).toHaveValue("Apple, Cherry");
  expect(await submitted()).toEqual(["cherry"]);

  await input.click();
  const list = page.getByRole("listbox", { name: "Fruit with disabled options", exact: true });
  await expect(list.getByRole("option")).toHaveText(["Apricot", "Cherry"]);
  await list.getByRole("option", { name: "Cherry", exact: true }).click();
  await expect(input).toHaveValue("Apple");
  expect(await submitted()).toEqual([]);

  await input.click();
  await list.getByRole("option", { name: "Apricot", exact: true }).click();
  await expect(input).toHaveValue("Apple, Apricot");
  expect(await submitted()).toEqual(["apricot"]);

  await input.evaluate((element) => {
    const root = element.closest("[data-combobox]");
    const value = root?.querySelector<HTMLInputElement>("[data-combobox-value]");
    if (!root || !value) throw new Error("Missing combobox state");
    value.value = "";
    root.dispatchEvent(new CustomEvent("combobox:sync", { detail: { options: [] } }));
  });
  await expect(input).toHaveValue("");
  expect(await submitted()).toEqual([]);
});

test("native multi-select also displays disabled selections without submitting them", async ({
  browser,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const page = await context.newPage();
    await page.goto("/design/");
    const form = page.getByRole("form", { name: "Fruit with disabled options", exact: true });
    await expect(form.getByRole("listbox")).toHaveValues(["apple", "cherry"]);
    expect(
      await form.evaluate((element) => new FormData(element as HTMLFormElement).getAll("fruit")),
    ).toEqual(["cherry"]);
  } finally {
    await context.close();
  }
});

test("a single disabled placeholder is omitted from form data until a pick is made", async ({
  page,
}) => {
  await page.goto("/design/");
  const input = page.getByRole("combobox", { name: "Fruit, unset", exact: true });
  await expect(input).toHaveValue("Choose a fruit…");
  await input.evaluate((element) => {
    const root = element.closest("[data-combobox]");
    if (!root) throw new Error("Missing combobox");
    const form = document.createElement("form");
    form.setAttribute("aria-label", "Placeholder submission");
    root.replaceWith(form);
    form.append(root);
  });
  const form = page.getByRole("form", { name: "Placeholder submission", exact: true });
  const submitted = () =>
    form.evaluate((element) => [...new FormData(element as HTMLFormElement).values()]);
  expect(await submitted()).toEqual([]);
  await input.click();
  await page.getByRole("option", { name: "Cherry", exact: true }).click();
  await expect(input).toHaveValue("Cherry");
  expect(await submitted()).toEqual(["cherry"]);
});
