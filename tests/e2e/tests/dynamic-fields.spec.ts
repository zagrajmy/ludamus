import { expect, test } from "./helpers/fixtures";

// Every organizer-defined field on the site renders through the `dynamic_field`
// tag, so these markup checks cover the panel and the wizard at once.
test.describe("Organizer-defined fields", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/event/open-mic/session/propose/");
    await page.getByLabel(/contact email/i).fill("anon@example.com");
    await page.getByRole("button", { name: /Continue/ }).click();
    await expect(
      page.locator('[id="wizard-content"]').getByRole("heading", { name: "Session Details" }),
    ).toBeVisible();
  });

  test("names a multi-select group with a legend instead of an orphan label", async ({ page }) => {
    const group = page.getByRole("group", { name: /^Tone/ });

    await expect(group).toBeVisible();
    await expect(group.locator('input[type="checkbox"]')).toHaveCount(2);
    await expect(group.locator('input[type="radio"]')).toHaveCount(0);
  });

  // A label opens with a capital but runs mostly lowercase, so its icon sits a
  // pixel below the capitals' middle: centred on the capitals it reads high,
  // and on the x-height middle (where `align-middle` put it) it reads low. The baseline is
  // read off a zero-height probe set beside the icon; the cap height off the
  // font the icon inherits.
  test("sets a field's icon a pixel below its label's cap middle", async ({ page }) => {
    const legend = page.getByRole("group", { name: /^Tone/ }).locator("legend");
    const { iconCentre, capCentre } = await legend.evaluate(async (node) => {
      await document.fonts.ready;
      const icon = node.querySelector("svg");
      const ctx = document.createElement("canvas").getContext("2d");
      if (!icon || !ctx) throw new Error("legend has no icon to measure");
      const probe = document.createElement("span");
      probe.style.cssText = "display:inline-block;width:0;height:0";
      icon.after(probe);
      const baseline = probe.getBoundingClientRect().bottom;
      probe.remove();
      ctx.font = getComputedStyle(icon).font;
      const capHeight = ctx.measureText("H").actualBoundingBoxAscent;
      const box = icon.getBoundingClientRect();
      return { iconCentre: box.top + box.height / 2, capCentre: baseline - capHeight / 2 };
    });

    expect(iconCentre - capCentre).toBeCloseTo(1, 0);
  });

  test("caps a text field's length and leaves its write-in requirement to the server", async ({
    page,
  }) => {
    const input = page.locator("#id_session_system");

    await expect(input).toHaveAttribute("maxlength", "40");
    // A write-in answers the question too, so the browser must not block on
    // the control alone — the form checks the pair.
    await expect(input).not.toHaveAttribute("required", "");
  });

  test("points the input at its help text", async ({ page }) => {
    const input = page.locator("#id_session_system");

    await expect(input).toHaveAttribute("aria-describedby", "id_session_system_help");
    await expect(page.locator("#id_session_system_help")).toContainText("Any edition is fine.");
  });

  test("gives the custom-value companion a name and the same length cap", async ({ page }) => {
    const companion = page.locator("#id_session_system_custom");

    await expect(companion).toHaveAttribute("aria-label", /custom value/i);
    await expect(companion).toHaveAttribute("maxlength", "40");
  });
});
