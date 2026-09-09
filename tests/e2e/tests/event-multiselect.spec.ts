import { expect, test } from "./helpers/fixtures";
import { DENSE_EVENT_URL } from "./helpers/urls";

const MEGA = "Open details for Mega Strategy Lab";
const COZY = "Open details for Cozy Storytellers Circle";
const NEON = "Open details for Przygoda w Mieście Neonów";

test("ORs hosts and locations within each filter, ANDs across filters", async ({ page }) => {
  await page.goto("/event/autumn-open/");
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  const host = page.getByRole("combobox", { name: "Host", exact: true });
  await host.click();
  await page.getByRole("option", { name: "Alex Morgan", exact: true }).click();
  await page.getByRole("option", { name: "Priya Chen", exact: true }).click();
  await expect(page.getByRole("link", { name: MEGA })).toBeVisible();
  await expect(page.getByRole("link", { name: COZY })).toBeVisible();
  await expect(page.getByRole("link", { name: NEON })).toBeHidden();

  await page.getByRole("combobox", { name: "Location", exact: true }).click();
  await page.getByRole("option", { name: "Main Hall — East Wing", exact: true }).click();
  await expect(page.getByRole("link", { name: COZY })).toBeHidden();
  await page.getByRole("option", { name: "Lounge — all rooms", exact: true }).click();
  await expect(page.getByRole("link", { name: COZY })).toBeVisible();
  await expect(page.getByRole("link", { name: MEGA })).toBeVisible();

  await page.getByRole("button", { name: "Remove filter: Alex Morgan", exact: true }).click();
  await expect(page.getByRole("link", { name: MEGA })).toBeHidden();
  await expect(page.getByRole("link", { name: COZY })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Remove filter: Priya Chen", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Clear all", exact: true }).click();
  await expect(page.getByRole("link", { name: MEGA })).toBeVisible();
  await expect(page.getByRole("link", { name: COZY })).toBeVisible();
  await expect(page.getByRole("link", { name: NEON })).toBeVisible();
  await expect.poll(() => new URL(page.url()).search).toBe("");
});

test("keyboard focus does not select, Enter toggles, Tab never toggles a pick back off", async ({
  page,
}) => {
  await page.goto("/event/autumn-open/");
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  const host = page.getByRole("combobox", { name: "Host", exact: true });
  await host.fill("chen");
  await host.press("ArrowDown");
  const priya = page.getByRole("option", { name: "Priya Chen", exact: true });
  await expect(priya).toHaveAttribute("aria-selected", "false");
  await host.press("Enter");
  await expect(priya).toHaveAttribute("aria-selected", "true");
  await host.press("Tab");
  await expect(host).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("button", { name: "Remove filter: Priya Chen" })).toBeVisible();
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  await host.click();
  await host.press("Enter");
  await expect(priya).toHaveAttribute("aria-selected", "false");
  await expect(page.getByRole("button", { name: "Remove filter: Priya Chen" })).toHaveCount(0);
  await host.fill("morgan");
  await host.press("Tab");
  await expect(page.getByRole("button", { name: /^Remove filter:/ })).toHaveCount(0);
});

test("multiple tracks survive reload, view navigation, and Back", async ({ page }) => {
  await page.goto(DENSE_EVENT_URL);
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  await page.getByRole("combobox", { name: "Track", exact: true }).click();
  await page.getByRole("option", { name: "Cosplay", exact: true }).click();
  await page.getByRole("option", { name: "RPG", exact: true }).click();
  const trackParam = JSON.stringify(["Cosplay", "RPG"]);
  await expect.poll(() => new URL(page.url()).searchParams.get("track")).toBe(trackParam);
  const results = page.getByRole("link", { name: /^Open details for / });
  const names = await results.allTextContents();
  expect(names.length).toBeGreaterThan(1);
  await page.reload();
  await expect(results).toHaveText(names);
  await expect(page.getByRole("button", { name: /^Remove filter:/ })).toHaveCount(2);
  await page.getByRole("tab", { name: "Rooms", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe("rooms");
  await expect(page.getByRole("button", { name: "Remove filter: Cosplay" })).toBeVisible();
  await page.getByRole("button", { name: "Remove filter: RPG", exact: true }).click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("track"))
    .toBe(JSON.stringify(["Cosplay"]));
  await page.goBack();
  await expect(page.getByRole("button", { name: "Remove filter: RPG", exact: true })).toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.get("track")).toBe(trackParam);
});

for (const raw of [
  JSON.stringify(["Priya Chen", "Priya Chen", "gone", "", null, 42]),
  "Priya Chen",
]) {
  test(`normalizes shared host selections: ${raw}`, async ({ page }) => {
    await page.goto(`/event/autumn-open/?host=${encodeURIComponent(raw)}&unrelated=keep`);
    await expect(page.getByRole("link", { name: COZY })).toBeVisible();
    await expect(page.getByRole("link", { name: MEGA })).toBeHidden();
    await expect(page.getByRole("button", { name: /^Remove filter:/ })).toHaveCount(1);
    await expect(page.getByRole("button", { name: "Remove filter: Priya Chen" })).toBeVisible();
    await expect
      .poll(() => new URL(page.url()).searchParams.get("host"))
      .toBe(JSON.stringify(["Priya Chen"]));
    expect(new URL(page.url()).searchParams.get("unrelated")).toBe("keep");
  });
}

for (const raw of ["[broken", '["gone"]', "[]", '[null,42,""]']) {
  test(`drops unusable host selections: ${raw}`, async ({ page }) => {
    await page.goto(`/event/autumn-open/?host=${encodeURIComponent(raw)}`);
    await expect(page.getByRole("link", { name: MEGA })).toBeVisible();
    await expect(page.getByRole("link", { name: COZY })).toBeVisible();
    await expect(page.getByRole("link", { name: NEON })).toBeVisible();
    await expect(page.getByRole("button", { name: /^Remove filter:/ })).toHaveCount(0);
    await expect.poll(() => new URL(page.url()).searchParams.has("host")).toBe(false);
  });
}

test("multi-select form submits repeated values like its native fallback", async ({ page }) => {
  await page.goto("/design/");
  const form = page.getByRole("form", { name: "Multiple fruit" });
  const fruit = form.getByRole("combobox", { name: "Multiple fruit" });
  const submitted = () =>
    form.evaluate((element) => new FormData(element as HTMLFormElement).getAll("fruit"));
  await expect(fruit).toHaveValue("Apple, Cherry");
  expect(await submitted()).toEqual(["apple", "cherry"]);
  await fruit.click();
  const list = page.getByRole("listbox", { name: "Multiple fruit" });
  await expect(list).toHaveAttribute("aria-multiselectable", "true");
  await list.getByRole("option", { name: "Apple", exact: true }).click();
  expect(await submitted()).toEqual(["cherry"]);
  await list.getByRole("option", { name: "Cherry", exact: true }).click();
  expect(await submitted()).toEqual([]);
  await list.getByRole("option", { name: "Apricot", exact: true }).click();
  expect(await submitted()).toEqual(["apricot"]);
});

test("scriptless multi-select retains native selections and form values", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("/design/");
  const form = page.getByRole("form", { name: "Multiple fruit" });
  const fruit = form.getByRole("listbox", { name: "Multiple fruit" });
  await expect(fruit).toHaveValues(["apple", "cherry"]);
  await fruit.selectOption(["apricot", "cherry"]);
  expect(
    await form.evaluate((element) => new FormData(element as HTMLFormElement).getAll("fruit")),
  ).toEqual(["apricot", "cherry"]);
  await context.close();
});

test("refreshes an open virtual list and prunes only removed selections", async ({ page }) => {
  await page.goto("/design/");
  const fruit = page.getByRole("combobox", { name: "Multiple fruit" });
  await fruit.click();
  await fruit.evaluate((input) => {
    input.closest("[data-combobox]")?.dispatchEvent(
      new CustomEvent("combobox:sync", {
        detail: { options: Array.from({ length: 200 }, (_, i) => [`value-${i}`, `Choice ${i}`]) },
      }),
    );
  });
  await fruit.fill("Choice 199");
  await page.getByRole("option", { name: "Choice 199", exact: true }).click();
  await fruit.press("Escape");
  await expect(fruit).toHaveValue("Apple, Cherry, Choice 199");
  await fruit.click();
  await fruit.evaluate((input) => {
    input.closest("[data-combobox]")?.dispatchEvent(
      new CustomEvent("combobox:sync", {
        detail: {
          options: [
            ["value-199", "Renamed choice"],
            ["", "Empty value"],
          ],
        },
      }),
    );
  });
  await expect(page.getByRole("option", { name: "Renamed choice", exact: true })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByRole("option", { name: "Choice 199", exact: true })).toHaveCount(0);
  await page.getByRole("option", { name: "Empty value", exact: true }).click();
  const form = page.getByRole("form", { name: "Multiple fruit" });
  expect(
    await form.evaluate((element) => new FormData(element as HTMLFormElement).getAll("fruit")),
  ).toEqual(["apple", "cherry", "value-199", ""]);
  await fruit.evaluate((input) => {
    input
      .closest("[data-combobox]")
      ?.dispatchEvent(new CustomEvent("combobox:sync", { detail: { options: [] } }));
  });
  await expect(fruit).toHaveValue("Apple, Cherry");
  await expect(
    page.getByRole("listbox", { name: "Multiple fruit" }).getByRole("option", { selected: true }),
  ).toHaveText(["Apple", "Cherry"]);
});
