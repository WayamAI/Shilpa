import { expect, test } from "@playwright/test";

/** Phone-width layout: no horizontal page scroll, and the navigation drawer works. */
test.use({ viewport: { width: 390, height: 844 } });

test("pages fit a phone viewport", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Enter studio" }).click();
  await expect(page).toHaveURL(/\/projects$/);

  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

  await page.screenshot({ path: "test-results/mobile-projects.png" });
  expect(await overflow()).toBeLessThanOrEqual(0);

  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("link", { name: "System" })).toBeVisible();
  await page.getByRole("link", { name: "System" }).click();
  await expect(page).toHaveURL(/\/system$/);
  await page.screenshot({ path: "test-results/mobile-system.png" });
  expect(await overflow()).toBeLessThanOrEqual(0);

  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "Parts catalogue" }).click();
  await expect(page).toHaveURL(/\/catalog$/);
  await expect(page.getByTestId("part-viewer")).toHaveAttribute("data-ready", "true", { timeout: 30_000 });
  await page.screenshot({ path: "test-results/mobile-catalog.png", fullPage: true });
  expect(await overflow()).toBeLessThanOrEqual(0);

  await page.goto("/projects");
  await page.getByRole("link").filter({ hasText: /parts?$/ }).first().click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("model-viewer")).toBeVisible();
  await page.screenshot({ path: "test-results/mobile-workspace.png", fullPage: true });
  expect(await overflow()).toBeLessThanOrEqual(0);
});
