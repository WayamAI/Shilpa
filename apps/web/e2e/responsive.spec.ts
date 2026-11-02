import { expect, test } from "@playwright/test";

import { overflowX, signInFast } from "./helpers";

/** Phone-width layout: no horizontal page scroll, the drawer works, the picker is a bottom sheet. */
test.use({ viewport: { width: 390, height: 844 } });

test("sign-in fits a phone", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByLabel("Work email")).toBeVisible();
  expect(await overflowX(page)).toBeLessThanOrEqual(0);
});

for (const route of ["/projects", "/library", "/compose", "/system"]) {
  test(`${route} has no horizontal scroll on a phone`, async ({ page, baseURL }) => {
    await signInFast(page, baseURL);
    await page.goto(route);
    await expect(page.getByRole("button", { name: "Open navigation" })).toBeVisible();
    await expect(page.getByRole("main")).toBeVisible();
    expect(await overflowX(page)).toBeLessThanOrEqual(0);
  });
}

test("phone chrome: tab bar shows, the desktop rail does not", async ({ page, baseURL }) => {
  await signInFast(page, baseURL);
  await page.goto("/library");
  await expect(page.getByRole("complementary", { name: "Sidebar" })).toBeHidden();
  const tabs = page.getByRole("navigation", { name: "Primary" });
  await expect(tabs.getByRole("link", { name: "Library" })).toHaveAttribute("aria-current", "page");
  await expect(tabs).toContainText("Needs you");
  await expect(tabs).toContainText("Home");
});

test("the navigation drawer opens, closes with Escape, and closes after navigating", async ({ page, baseURL }) => {
  await signInFast(page, baseURL);
  await page.goto("/projects");
  const open = page.getByRole("button", { name: "Open navigation" });
  const drawer = page.getByRole("dialog", { name: "Navigation" });
  await open.click();
  await expect(drawer).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();

  await open.click();
  await drawer.getByRole("link", { name: "Library" }).click();
  await expect(page).toHaveURL(/\/library$/);
  await expect(drawer).toBeHidden();
});

test("the @ picker is a bottom sheet on a phone", async ({ page, baseURL }) => {
  await signInFast(page, baseURL);
  await page.goto("/compose");
  const prompt = page.getByRole("combobox", { name: "Composition prompt" });
  await prompt.click();
  await prompt.pressSequentially("@");
  const list = page.getByRole("listbox", { name: "Parts" });
  await expect(list.getByRole("option").first()).toBeVisible();
  const box = (await list.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.width).toBeGreaterThanOrEqual(viewport.width - 4); // full width (minus the sheet border)
  expect(Math.abs(box.y + box.height - viewport.height)).toBeLessThanOrEqual(3); // docked to the bottom edge
  expect(box.height).toBeLessThanOrEqual(viewport.height * 0.7);
  await expect(page.getByRole("button", { name: "Close picker" })).toBeAttached(); // scrim
  expect(await overflowX(page)).toBeLessThanOrEqual(0);

  await prompt.press("Enter");
  await expect(page.getByRole("button", { name: /, change reference$/ })).toHaveCount(1);
  await expect(list).toBeHidden();
});

test("the project workspace fits a phone", async ({ page, baseURL }) => {
  await signInFast(page, baseURL);
  await page.goto("/projects");
  await page.getByRole("link").filter({ hasText: /parts?$/ }).first().click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { level: 2 }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "All projects" })).toBeVisible();
  expect(await overflowX(page)).toBeLessThanOrEqual(0);
});
