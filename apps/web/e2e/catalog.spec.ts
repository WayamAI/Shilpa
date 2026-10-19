import { expect, test } from "@playwright/test";

/**
 * Parts catalogue: browse, edit a parameter, see the part rebuild, inspect ports and data.
 * Previews build synchronously on the API (about a second each), no AI involved.
 */

test.beforeEach(async ({ context, baseURL }) => {
  await context.addCookies([{ name: "shilpa-session", value: encodeURIComponent("dev@wayam.local"), url: baseURL! }]);
});

test("browse gears, change the tooth count, inspect ports", async ({ page }, info) => {
  await page.goto("/catalog");
  await expect(page.getByRole("main").getByRole("heading", { name: "Parts catalogue" })).toBeVisible();
  const list = page.getByTestId("catalog-list");
  await expect(list.getByText("Gears ·", { exact: false })).toBeVisible();

  await list.getByRole("button", { name: /Involute spur gear/ }).click();
  await expect(page.getByTestId("part-viewer")).toHaveAttribute("data-ready", "true", { timeout: 30_000 });
  await expect(page.getByText(/44 × 44 × 10 mm/)).toBeVisible({ timeout: 30_000 });

  await page.getByRole("spinbutton", { name: "Teeth" }).fill("40");
  await expect(page.getByText(/84 × 84 × 10 mm/)).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: info.outputPath("catalog-gear.png") });

  await page.getByRole("tab", { name: /Ports/ }).click();
  const ports = page.getByTestId("port-list");
  await expect(ports.getByText("mesh", { exact: true })).toBeVisible();
  await ports.getByRole("button", { name: /bore_axis/ }).click();
  await expect(ports.getByRole("button", { name: /bore_axis/ })).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("tab", { name: "Data" }).click();
  await expect(page.getByText("spur m2 z40").first()).toBeVisible();
});

test("an invalid size explains itself, and the V-slot rail builds", async ({ page }, info) => {
  await page.goto("/catalog");
  await page.getByLabel("Search parts").fill("v-slot");
  await page.getByTestId("catalog-list").getByRole("button", { name: /aluminium extrusion/ }).click();
  await page.getByRole("combobox", { name: "Profile" }).selectOption("4040");
  await expect(page.getByText(/40 × 40 × 250 mm/)).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: info.outputPath("catalog-vslot.png") });

  await page.getByLabel("Search parts").fill("spur");
  await page.getByTestId("catalog-list").getByRole("button", { name: /Involute spur gear/ }).click();
  await page.getByRole("spinbutton", { name: "Bore d" }).fill("60");
  await expect(page.getByTestId("build-error")).toContainText("web", { timeout: 30_000 });
});

test("screws come from the standards' tables, lengths included", async ({ page }, info) => {
  await page.goto("/catalog");
  await page.getByLabel("Search parts").fill("socket head cap");
  await page.getByTestId("catalog-list").getByRole("button", { name: /Socket head cap screw \(ASME/ }).click();
  await expect(page.getByText(/ISO 4762 M6-1 x 16/).first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole("spinbutton", { name: "Length" }).fill("21");
  await expect(page.getByTestId("build-error")).toContainText("not a nominal iso4762 length", { timeout: 30_000 });
  await page.getByRole("spinbutton", { name: "Length" }).fill("25");
  await page.getByRole("combobox", { name: "Size" }).selectOption("M8-1.25");
  await expect(page.getByText(/ISO 4762 M8-1.25 x 25/).first()).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: info.outputPath("catalog-screw.png") });
});
