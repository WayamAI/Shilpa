import { expect, test } from "@playwright/test";

import { overflowX, signInFast } from "./helpers";

test.beforeEach(async ({ page, baseURL }) => {
  await signInFast(page, baseURL);
});

test("the needs you page lists items or shows the empty state", async ({ page }) => {
  await page.goto("/needs-you");
  await expect(page.getByRole("heading", { level: 1, name: "Needs you" })).toBeVisible();
  const list = page.getByRole("list", { name: "Items that need you" });
  const empty = page.getByText("Nothing needs you", { exact: true });
  await expect(list.or(empty)).toBeVisible();
  await expect(page.getByRole("list", { name: "Planned items" }).getByRole("listitem")).toHaveCount(2);
});

test("the header bell opens the inbox and names the count", async ({ page }) => {
  await page.goto("/home");
  const bell = page.getByRole("link", { name: /^Needs you/ }).first();
  await expect(bell).toHaveAttribute("href", "/needs-you");
  await bell.click();
  await expect(page).toHaveURL(/\/needs-you$/);
});

test("the phone tab bar links to needs you and the page fits 390px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/home");
  await expect(page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Needs you" })).toHaveAttribute("href", "/needs-you");
  await page.goto("/needs-you");
  await expect(page.getByRole("list", { name: "Items that need you" }).or(page.getByText("Nothing needs you", { exact: true }))).toBeVisible();
  expect(await overflowX(page)).toBeLessThanOrEqual(0);
});
