import { expect, test, type Page } from "@playwright/test";

/**
 * Assemblies and sheet metal from the reference starters. None of this needs the AI
 * planner, so these tests run with SHILPA_LLM=off.
 */

const SHOTS = "test-results/screens";

async function signIn(page: Page, email = "dev@wayam.local") {
  await page.goto("/login");
  await page.getByLabel("Engineer").selectOption(email);
  await page.getByRole("button", { name: "Enter studio" }).click();
  await expect(page).toHaveURL(/\/projects$/);
}

async function newProject(page: Page, name: string) {
  await page.getByLabel("New project name").fill(name);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
}

async function lastJobSucceeds(page: Page, timeout = 120_000) {
  const card = page.getByTestId("job-card").last();
  await expect(card).toHaveAttribute("data-state", /succeeded|failed|cancelled/, { timeout });
  await expect(card).toHaveAttribute("data-state", "succeeded");
}

async function startFrom(page: Page, value: string) {
  await page.getByLabel("Start from a reference assembly or sheet-metal part").selectOption(value);
  await lastJobSucceeds(page);
}

async function setTheme(page: Page, theme: "light" | "dark") {
  const html = page.locator("html");
  if ((await html.getAttribute("data-theme")) !== theme) {
    await page.getByRole("button", { name: theme === "dark" ? "Switch to dark" : "Switch to light" }).click();
    await expect(html).toHaveAttribute("data-theme", theme);
    await page.waitForTimeout(400); // let the 180 ms colour transitions settle before a screenshot
  }
}

const viewer = (page: Page) => page.getByTestId("assembly-viewer").first();

test("hinge: parts tree, BOM, checks, joint scrub and STEP download", async ({ page }) => {
  await signIn(page);
  await newProject(page, `E2E hinge ${Date.now()}`);
  await startFrom(page, "assembly:hinge");

  await expect(viewer(page)).toHaveAttribute("data-ready", "true");
  const tree = page.getByTestId("parts-tree");
  await expect(tree.getByRole("treeitem")).toHaveCount(3);
  await expect(page.getByText("all checks passed").first()).toBeVisible();

  // Selecting in the tree selects in the viewer.
  await tree.getByRole("treeitem").filter({ hasText: "lid" }).getByRole("button").click();
  await expect(viewer(page)).toHaveAttribute("data-selected", "lid");
  await setTheme(page, "light");
  await page.screenshot({ path: `${SHOTS}/hinge-parts-light.png` });

  await page.getByRole("tab", { name: "BOM" }).click();
  await expect(page.getByTestId("bom-table").locator("tbody tr")).toHaveCount(3);

  await page.getByRole("tab", { name: "Checks" }).click();
  const checks = page.getByTestId("checks-panel");
  await expect(checks.getByText(/^all \d+ checks passed$/)).toBeVisible();
  for (const name of ["interference", "dof", "sweep[hinge]", "clearance[lid+pin]", "contact[base.pin_seat~pin.seat]"]) {
    await expect(checks.locator(`[data-check="${name}"]`)).toHaveAttribute("data-passed", "true");
  }

  // Scrub the hinge: the lid swings about the pin axis.
  await page.getByRole("tab", { name: "Joints" }).click();
  await page.getByLabel("hinge joint angle").fill("60");
  await expect(page.getByTestId("joint-value-hinge")).toHaveText("60 deg");
  await expect(viewer(page)).toHaveAttribute("data-joints", /"hinge":60/);
  await setTheme(page, "dark");
  await page.screenshot({ path: `${SHOTS}/hinge-joint-dark.png` });
  await page.getByRole("button", { name: "Reset hinge" }).click();
  await expect(page.getByTestId("joint-value-hinge")).toHaveText("0 deg");

  await page.getByRole("tab", { name: "Files" }).click();
  await expect(page.getByRole("button", { name: "Download BOM (CSV)" })).toBeVisible();
  await expect(page.getByText("1 version · each change is a new immutable version")).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download STEP" }).click();
  expect((await download).suggestedFilename()).toMatch(/\.step$/);
  await setTheme(page, "light");
});

test("interfering golden: the clash is listed and highlighted", async ({ page }) => {
  await signIn(page);
  await newProject(page, `E2E clash ${Date.now()}`);
  await startFrom(page, "assembly:interfering");

  await expect(page.getByText("checks failed").first()).toBeVisible();
  const checks = page.getByTestId("checks-panel"); // a failing assembly opens on Checks
  await expect(checks.getByText(/^2 of \d+ failed$/)).toBeVisible();
  const clash = checks.locator('[data-check="interference[block+plate]"]');
  await expect(clash).toHaveAttribute("data-passed", "false");
  await expect(clash).toContainText("800 mm³ overlap");
  await clash.getByRole("button").click();
  await expect(viewer(page)).toHaveAttribute("data-highlight", "block,plate");

  // The tree marks both parts.
  await page.getByRole("tab", { name: "Parts" }).click();
  await expect(page.getByTestId("parts-tree").getByTitle("Involved in a failed check")).toHaveCount(2);
  await page.getByRole("tab", { name: "Checks" }).click();
  await page.screenshot({ path: `${SHOTS}/interference-light.png` });
  await setTheme(page, "dark");
  await page.screenshot({ path: `${SHOTS}/interference-dark.png` });
  await setTheme(page, "light");
});

test("sheet metal: folded part, flat pattern and bend table", async ({ page }) => {
  await signIn(page);
  await newProject(page, `E2E sheet ${Date.now()}`);
  await startFrom(page, "sheet_metal:l_bracket");

  const flat = page.getByTestId("flat-pattern");
  await expect(flat).toBeVisible();
  await expect(flat.getByRole("img", { name: /^Flat pattern 100 × 80\.16 mm$/ })).toBeVisible();
  await expect(page.getByTestId("flat-size")).toHaveText("100 × 80.163 mm");
  await expect(page.getByTestId("bend-table").locator("tbody tr")).toHaveCount(1);
  await expect(viewer(page)).toHaveAttribute("data-ready", "true");
  await page.screenshot({ path: `${SHOTS}/sheet-metal-light.png` });
  await page.getByRole("tab", { name: "Checks" }).click();
  await expect(page.getByTestId("sheet-checks").getByText(/^all \d+ checks passed$/)).toBeVisible();
  await setTheme(page, "dark");
  await page.screenshot({ path: `${SHOTS}/sheet-metal-dark.png` });
  await setTheme(page, "light");

  await page.getByRole("tab", { name: "Export" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download Flat pattern (DXF)" }).click();
  expect((await download).suggestedFilename()).toMatch(/_flat\.dxf$/);
});

test("planner disabled: requests are routed and explained", async ({ page }) => {
  const health = await (await page.request.get("/v1/health")).json();
  test.skip(health.planner !== "disabled", "only meaningful with SHILPA_LLM=off");
  await signIn(page);
  await newProject(page, `E2E route ${Date.now()}`);
  await expect(page.getByTestId("planner-disabled")).toBeVisible();
  await page.getByLabel("Describe a part").fill("A hinge assembly with a lid that swings 100 degrees");
  await page.getByRole("button", { name: "Route" }).click();
  await expect(page.getByText(/This reads as an assembly\. The AI planner is disabled/)).toBeVisible();
  await page.getByLabel("Describe a part").fill("Design a PCB for my robot");
  await page.getByRole("button", { name: "Route" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Not supported" })).toBeVisible();
});

test.describe("narrow width", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("assembly and sheet-metal views fit a phone", async ({ page }) => {
    await signIn(page);
    await newProject(page, `E2E narrow ${Date.now()}`);
    await startFrom(page, "assembly:lid_hits_wall");
    await expect(page.getByTestId("checks-panel").locator('[data-check="sweep[hinge]"]')).toHaveAttribute("data-passed", "false");
    const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(await overflow()).toBeLessThanOrEqual(0);
    await page.screenshot({ path: `${SHOTS}/narrow-assembly.png`, fullPage: true });
    await viewer(page).scrollIntoViewIfNeeded();
    await expect(viewer(page)).toHaveAttribute("data-ready", "true");
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${SHOTS}/narrow-assembly-viewer.png` });

    await startFrom(page, "sheet_metal:enclosure_tray");
    await expect(page.getByTestId("flat-pattern")).toBeVisible();
    expect(await overflow()).toBeLessThanOrEqual(0);
    await page.screenshot({ path: `${SHOTS}/narrow-sheet-metal.png`, fullPage: true });
    await page.getByTestId("flat-pattern").scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${SHOTS}/narrow-flat-pattern.png` });
  });
});
