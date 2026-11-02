import { expect, test } from "@playwright/test";

import { overflowX, signInFast } from "./helpers";

test.beforeEach(async ({ page, baseURL }) => {
  await signInFast(page, baseURL);
  await page.goto("/home");
});

test("home greets the user and offers the composer", async ({ page }) => {
  await expect(page.getByRole("heading", { level: 1, name: /^What are we building today/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open composer" }).first()).toHaveAttribute("href", "/compose");
});

test("needs you shows real items or the empty state, and lists planned kinds", async ({ page }) => {
  await expect(page.getByRole("heading", { level: 2, name: "Needs you" })).toBeVisible();
  const real = page.getByRole("list", { name: "Items that need you" });
  const empty = page.getByText("Nothing needs you", { exact: true });
  await expect(real.or(empty)).toBeVisible();
  const planned = page.getByRole("list", { name: "Planned items" });
  await expect(planned.getByRole("listitem")).toHaveCount(3);
  await expect(planned.getByText("Planned")).toHaveCount(3);
});

test("recent complex parts shows rows or an empty state", async ({ page }) => {
  await expect(page.getByRole("heading", { level: 2, name: "Recent complex parts" })).toBeVisible();
  const rows = page.getByRole("list", { name: "Recent complex parts" });
  const empty = page.getByText("No complex parts yet", { exact: true });
  await expect(rows.or(empty)).toBeVisible();
});

test("the Home nav link is live and the page fits a phone", async ({ page }) => {
  await expect(page.getByRole("complementary", { name: "Sidebar" }).getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(await overflowX(page)).toBeLessThanOrEqual(0);
});
