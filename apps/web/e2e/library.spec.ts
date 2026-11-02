import { expect, test, type Page } from "@playwright/test";

import { signInFast } from "./helpers";

test.beforeEach(async ({ page, baseURL }) => {
  await signInFast(page, baseURL);
  await page.goto("/library");
});

const parts = (page: Page) => page.getByRole("list", { name: "Parts" }).getByRole("listitem");

test("the library loads the catalog parts", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Library", level: 1 })).toBeVisible();
  await expect(parts(page).first()).toBeVisible();
  expect(await parts(page).count()).toBeGreaterThan(10);
  await expect(page.getByRole("radiogroup", { name: "Part kind" }).getByRole("radio", { name: /^All/ })).toHaveAttribute("aria-checked", "true");
});

test("the kind filter narrows to basic or complex parts", async ({ page }) => {
  await expect(parts(page).first()).toBeVisible();
  const all = await parts(page).count();
  const kind = page.getByRole("radiogroup", { name: "Part kind" });

  await kind.getByRole("radio", { name: /^Basic/ }).click();
  await expect(kind.getByRole("radio", { name: /^Basic/ })).toHaveAttribute("aria-checked", "true");
  await expect(parts(page).first()).toBeVisible();
  expect(await parts(page).count()).toBeLessThanOrEqual(all);
  await expect(parts(page).filter({ hasText: "Complex" })).toHaveCount(0);

  await kind.getByRole("radio", { name: /^Complex/ }).click();
  await expect(kind.getByRole("radio", { name: /^Complex/ })).toHaveAttribute("aria-checked", "true");
  await expect(parts(page).filter({ hasText: "Basic" })).toHaveCount(0);
});

test("search narrows results, and clearing the filters restores them", async ({ page }) => {
  await expect(parts(page).first()).toBeVisible();
  const all = await parts(page).count();

  await page.getByLabel("Search parts").fill("spur");
  await expect(parts(page).filter({ hasText: /spur/i }).first()).toBeVisible();
  await expect.poll(() => parts(page).count()).toBeLessThan(all);

  await page.getByLabel("Search parts").fill("zzzz-no-such-part");
  await expect(page.getByText("No parts match")).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page.getByLabel("Search parts")).toHaveValue("");
  await expect.poll(() => parts(page).count()).toBe(all);
});

test("a catalog part opens its catalog page with the generator selected", async ({ page }) => {
  await page.getByLabel("Search parts").fill("spur");
  await parts(page).first().getByRole("link").click();
  await expect(page).toHaveURL(/\/catalog\?gen=/);
  await expect(page.getByTestId("part-viewer")).toBeVisible();
});

test("Import is shown as planned and disabled; New complex part goes to the composer", async ({ page }) => {
  await expect(page.getByRole("button", { name: /Import STEP \/ STL/ })).toBeDisabled();
  await page.getByRole("link", { name: "New complex part" }).click();
  await expect(page).toHaveURL(/\/compose$/);
});
