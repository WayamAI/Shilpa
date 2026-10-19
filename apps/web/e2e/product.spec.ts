import { expect, test, type Page } from "@playwright/test";

/**
 * Template products (bicycle) through the job queue. The request parser is rule-based, so
 * these run with SHILPA_LLM=off. One bike takes about 30 s to build, check and render.
 */

const SHOTS = "test-results/screens";
const STARTERS = "Start from a reference assembly, sheet-metal part or product";

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Engineer").selectOption("dev@wayam.local");
  await page.getByRole("button", { name: "Enter studio" }).click();
  await expect(page).toHaveURL(/\/projects$/);
}

async function newProject(page: Page, name: string) {
  await page.getByLabel("New project name").fill(name);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);
}

async function lastJobSucceeds(page: Page, timeout = 240_000) {
  const card = page.getByTestId("job-card").last();
  await expect(card).toHaveAttribute("data-state", /succeeded|failed|cancelled/, { timeout });
  await expect(card).toHaveAttribute("data-state", "succeeded");
}

async function setTheme(page: Page, theme: "light" | "dark") {
  const html = page.locator("html");
  if ((await html.getAttribute("data-theme")) !== theme) {
    await page.getByRole("button", { name: theme === "dark" ? "Switch to dark" : "Switch to light" }).click();
    await expect(html).toHaveAttribute("data-theme", theme);
    await page.waitForTimeout(400);
  }
}

test.beforeEach(async ({ page }) => {
  const health = await (await page.request.get("/v1/health")).json();
  test.skip(!health.products_available, "product templates not installed");
});

test("reference road bike: parts, checks, router log, renders and STEP", async ({ page }) => {
  test.setTimeout(300_000);
  await signIn(page);
  await newProject(page, `E2E bike ${Date.now()}`);
  await page.getByLabel(STARTERS).selectOption("product:road_m");
  const card = page.getByTestId("job-card").last();
  await expect(card.getByText(/offline template parser/)).toBeVisible({ timeout: 60_000 }); // progress events stream in
  await lastJobSucceeds(page);

  const viewer = page.getByTestId("assembly-viewer").first();
  await expect(viewer).toHaveAttribute("data-ready", "true", { timeout: 60_000 });
  const tree = page.getByTestId("parts-tree");
  expect(await tree.getByRole("treeitem").count()).toBeGreaterThan(10);
  await expect(page.getByTestId("joints-panel").locator('[data-joint="steering"]')).toBeVisible();
  await setTheme(page, "light");
  await page.screenshot({ path: `${SHOTS}/product-parts-light.png` });

  await page.getByRole("tab", { name: "BOM" }).click();
  expect(await page.getByTestId("bom-table").locator("tbody tr").count()).toBeGreaterThan(10);

  await page.getByRole("tab", { name: "Checks" }).click();
  const checks = page.getByTestId("checks-panel");
  await expect(checks.getByText(/^all \d+ checks passed$/)).toBeVisible();
  const tyre = checks.locator('[data-check="tyre_clearance[front_tyre~fork]"]');
  await expect(tyre).toHaveAttribute("data-passed", "true");
  await tyre.getByRole("button").click();
  await expect(viewer).toHaveAttribute("data-highlight", /front_tyre/);
  await page.screenshot({ path: `${SHOTS}/product-checks-light.png` });

  await page.getByRole("tab", { name: "Router" }).click();
  const router = page.getByTestId("router-panel");
  await expect(router.getByText("passed").first()).toBeVisible();
  await expect(router.locator("[data-iteration]")).toHaveCount(1);
  await expect(page.getByTestId("skeleton-table")).toContainText("rider height");
  await setTheme(page, "dark");
  await page.screenshot({ path: `${SHOTS}/product-router-dark.png` });

  await page.getByRole("tab", { name: "Files" }).click();
  await expect(page.getByRole("img", { name: "Side view" })).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: `${SHOTS}/product-files-dark.png` });
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download STEP" }).click();
  expect((await download).suggestedFilename()).toMatch(/\.step$/);
  await setTheme(page, "light");
});

test("typed bike request runs the template offline", async ({ page }) => {
  test.setTimeout(300_000);
  await signIn(page);
  await newProject(page, `E2E bike prompt ${Date.now()}`);
  await page.getByLabel("Describe a part").fill("650b gravel bike small rider 45 mm tyres");
  await page.getByRole("button", { name: /^(Route|Send)$/ }).click();
  await expect(page.getByText(/This reads as a product/)).toBeVisible();
  await lastJobSucceeds(page);
  await expect(page.getByText(/bicycle_gravel_s/).first()).toBeVisible();
});

test("wide tyres: the router repairs the design", async ({ page }) => {
  test.setTimeout(360_000);
  await signIn(page);
  await newProject(page, `E2E bike repair ${Date.now()}`);
  await page.getByLabel(STARTERS).selectOption("product:wide_tyres");
  await lastJobSucceeds(page, 300_000);
  await page.getByRole("tab", { name: "Router" }).click();
  const router = page.getByTestId("router-panel");
  await expect(router.getByText("repaired").first()).toBeVisible();
  expect(await router.locator("[data-iteration]").count()).toBeGreaterThan(1);
  await expect(router.getByText(/^Changes · \d+$/)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/product-repaired-light.png` });
});
