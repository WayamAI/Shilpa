import { expect, test, type Page } from "@playwright/test";

import { signInFast } from "./helpers";

test.beforeEach(async ({ page, baseURL }) => {
  await signInFast(page, baseURL);
  await page.goto("/compose");
});

const prompt = (page: Page) => page.getByRole("combobox", { name: "Composition prompt" });
const chips = (page: Page) => page.getByRole("button", { name: /, change reference$/ });
const options = (page: Page) => page.getByRole("listbox", { name: "Parts" }).getByRole("option");

async function openPicker(page: Page) {
  await prompt(page).click();
  await prompt(page).pressSequentially("@");
  await expect(options(page).first()).toBeVisible();
}

test("typing @ opens the parts listbox and Escape closes it", async ({ page }) => {
  await expect(prompt(page)).toHaveAttribute("aria-expanded", "false");
  await openPicker(page);
  await expect(prompt(page)).toHaveAttribute("aria-expanded", "true");
  await prompt(page).press("Escape");
  await expect(page.getByRole("listbox", { name: "Parts" })).toBeHidden();
  await expect(prompt(page)).toHaveAttribute("aria-expanded", "false");
});

test("the query after @ filters the options", async ({ page }) => {
  await openPicker(page);
  const before = await options(page).count();
  await prompt(page).pressSequentially("spur");
  await expect(options(page).filter({ hasText: /spur/i }).first()).toBeVisible();
  await expect.poll(() => options(page).count()).toBeLessThan(before);
});

test("Enter inserts a chip that shows under resolved references", async ({ page }) => {
  await openPicker(page);
  const name = (await options(page).first().innerText()).split("\n")[0].trim();

  await prompt(page).press("Enter");
  await expect(chips(page)).toHaveCount(1);
  await expect(chips(page)).toHaveAccessibleName(`@${name}, change reference`);
  await expect(page.getByRole("listbox", { name: "Parts" })).toBeHidden();
  await expect(prompt(page)).toHaveValue("");
  await expect(page.getByRole("complementary").getByText(`@${name}`)).toBeVisible();
});

test("Backspace removes the whole chip in one keystroke", async ({ page }) => {
  await openPicker(page);
  await prompt(page).press("Enter");
  await expect(chips(page)).toHaveCount(1);
  await prompt(page).press("Backspace");
  await expect(chips(page)).toHaveCount(0);
});

test("ArrowDown moves the active option and Enter inserts it", async ({ page }) => {
  await openPicker(page);
  await expect(options(page).nth(1)).toBeVisible();
  await expect(options(page).first()).toHaveAttribute("aria-selected", "true");
  await prompt(page).press("ArrowDown");
  await expect(options(page).nth(1)).toHaveAttribute("aria-selected", "true");
  const second = (await options(page).nth(1).innerText()).split("\n")[0].trim();
  await prompt(page).press("Enter");
  await expect(chips(page)).toHaveAccessibleName(`@${second}, change reference`);
});

test("Interpret is planned and disabled", async ({ page }) => {
  await expect(page.getByRole("button", { name: "Interpret" })).toBeDisabled();
});

test("a read-only user sees no prompt", async ({ page, baseURL }) => {
  await page.context().clearCookies();
  await signInFast(page, baseURL, "viewer@wayam.local");
  await page.goto("/compose");
  await expect(page.getByText("You have read-only access")).toBeVisible();
  await expect(prompt(page)).toHaveCount(0);
});
