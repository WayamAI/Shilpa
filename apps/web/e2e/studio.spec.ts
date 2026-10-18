import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const DRAWINGS = path.resolve(__dirname, "../../../evals/drawings");

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

/** Wait for the newest job card to finish and assert it succeeded. */
async function lastJobSucceeds(page: Page, timeout = 120_000) {
  const card = page.getByTestId("job-card").last();
  await expect(card).toHaveAttribute("data-state", /succeeded|failed|cancelled/, { timeout });
  await expect(card).toHaveAttribute("data-state", "succeeded");
}

const sizeChip = (page: Page) => page.getByTestId("model-viewer").getByText(/ mm$/).last();

test("sign-in gate redirects and admits the dev engineer", async ({ page }) => {
  await page.goto("/projects");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await signIn(page);
  await expect(page.getByTitle("Azure OpenAI planner")).toContainText("Online");
  await expect(page.getByRole("heading", { name: "Projects", level: 2, exact: true })).toBeVisible();
});

test("reference part, parameter edit, restore and FreeCAD export", async ({ page }) => {
  await signIn(page);
  await newProject(page, `E2E plate ${Date.now()}`);
  await expect(page.getByText("No part yet")).toBeVisible();

  // Reference part P01: the analytic plate.
  await page.getByLabel("Start from a reference part").selectOption("P01");
  await lastJobSucceeds(page);
  await expect(sizeChip(page)).toHaveText("80 × 40 × 8 mm");
  await page.getByRole("tab", { name: "Checks" }).click();
  await expect(page.getByText("all checks passed")).toBeVisible();
  await expect(page.getByText("4× Ø6")).toBeVisible();

  // Parameter edit: width 100 -> new version, holes stay 10 mm from the edges.
  await page.getByRole("tab", { name: "Parameters" }).click();
  await page.getByLabel("width").fill("100");
  await page.getByRole("button", { name: "Apply as new version" }).click();
  await lastJobSucceeds(page);
  await expect(sizeChip(page)).toHaveText("100 × 40 × 8 mm");

  // Versions: two exist; restore v1 as v3.
  await page.getByRole("tab", { name: "Versions" }).click();
  await expect(page.getByText("2 versions")).toBeVisible();
  await page.getByRole("button", { name: "Restore" }).click();
  await lastJobSucceeds(page);
  await expect(sizeChip(page)).toHaveText("80 × 40 × 8 mm");
  await page.getByRole("tab", { name: "Versions" }).click();
  await expect(page.getByText("3 versions")).toBeVisible();

  // Native FreeCAD export derivative.
  await page.getByRole("tab", { name: "Export" }).click();
  await page.getByRole("button", { name: "Create FreeCAD file" }).click();
  await lastJobSucceeds(page, 180_000);
  await expect(page.getByRole("button", { name: "Download FreeCAD" })).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download STEP" }).click();
  expect((await download).suggestedFilename()).toMatch(/\.step$/);
});

test("drawing upload, review and generation", async ({ page }) => {
  await signIn(page);
  await newProject(page, `E2E drawing ${Date.now()}`);
  await page.getByTestId("drawing-input").setInputFiles(path.join(DRAWINGS, "P01_vector.pdf"));

  const dialog = page.getByRole("dialog", { name: "Review values read from the drawing" });
  await expect(dialog).toBeVisible({ timeout: 150_000 });
  await expect(dialog.getByRole("img", { name: "Drawing page 1" })).toBeVisible();
  await expect(dialog.getByText("text ✓").first()).toBeVisible();
  await dialog.getByRole("button", { name: "Confirm values" }).click();
  await expect(dialog).toBeHidden();

  await page.getByRole("button", { name: "Generate CAD" }).click();
  await lastJobSucceeds(page, 150_000);
  await expect(sizeChip(page)).toHaveText("80 × 40 × 8 mm");
});

test("language request with a clarifying question", async ({ page }) => {
  await signIn(page);
  await newProject(page, `E2E language ${Date.now()}`);
  await page.getByLabel("Describe a part").fill("Steel spacer with 20 mm OD and 10 mm ID.");
  await page.getByRole("button", { name: "Send" }).click();
  const spec = page.getByTestId("spec-card").last();
  await expect(spec.getByText("needs answers")).toBeVisible({ timeout: 90_000 });
  await spec.locator("input").first().fill("12");
  await spec.getByRole("button", { name: "Answer" }).click();
  await expect(spec.getByText("ready")).toBeVisible();
  await spec.getByRole("button", { name: "Generate CAD" }).click();
  await lastJobSucceeds(page, 150_000);
  await expect(sizeChip(page)).toHaveText("20 × 20 × 12 mm");
});

test("read-only role cannot edit", async ({ page }) => {
  await signIn(page, "viewer@wayam.local");
  await expect(page.getByLabel("New project name")).toHaveCount(0);
  await page.getByRole("link").filter({ hasText: /parts?$/ }).first().click();
  await expect(page.getByText("Read-only role")).toBeVisible();
  await expect(page.getByLabel("Describe a part")).toHaveCount(0);
});

test("another tenant cannot open a project", async ({ page, context }) => {
  await signIn(page);
  await page.getByRole("link").filter({ hasText: /parts?$/ }).first().click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);
  const url = page.url();
  await context.clearCookies();
  await signIn(page, "other@example.com");
  await page.goto(url);
  await expect(page.getByText("This project could not be opened")).toBeVisible();
});

test("theme toggle persists across reloads", async ({ page }) => {
  await signIn(page);
  const html = page.locator("html");
  const start = await html.getAttribute("data-theme");
  await page.getByRole("button", { name: start === "dark" ? "Switch to light" : "Switch to dark" }).click();
  const flipped = start === "dark" ? "light" : "dark";
  await expect(html).toHaveAttribute("data-theme", flipped);
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", flipped);
  await page.getByRole("button", { name: flipped === "dark" ? "Switch to light" : "Switch to dark" }).click();
});

test("sign out returns to sign-in", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/projects");
  await expect(page).toHaveURL(/\/login$/);
});
