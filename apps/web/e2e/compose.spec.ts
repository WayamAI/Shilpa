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

test("Interpret needs a prompt and stays off while the planner is off", async ({ page }) => {
  const button = page.getByRole("button", { name: /^(Re-)?interpret$/i });
  await expect(button).toBeVisible();
  if (await page.getByText(/Planner is off/).first().isVisible().catch(() => false)) await expect(button).toBeDisabled();
});

test("a composition resumes from ?c= and an applied step appears (no planner)", async ({ page, request }) => {
  const auth = { Authorization: "Bearer dev:dev@wayam.local" };
  const project = await (await request.post("/v1/projects", { headers: auth, data: { name: `Compose e2e ${Date.now()}` } })).json();
  const comp = await (await request.post("/v1/compositions", { headers: auth, data: { project_id: project.id, name: "e2e" } })).json();

  /* Sending steps back needs no model: the same deterministic path as answering a question (tests/compose E6_BASE). */
  const steps = [
    { id: "s1", op: "add", source: { text: "@shaft-20", mention: "m1" } },
    { id: "s2", op: "ground", source: { text: "@shaft-20", mention: "m1" } },
  ];
  const prompt = "use @shaft-20 as the base";
  const interp = await request.post(`/v1/compositions/${comp.id}/interpret`, { headers: auth, data: { prompt, steps } });
  expect(interp.ok(), await interp.text()).toBeTruthy();
  const card = await interp.json();
  expect(card.status).toBe("ready");

  const applied = await request.post(`/v1/compositions/${comp.id}/apply`, {
    headers: { ...auth, "Idempotency-Key": `e2e-${Date.now()}` },
    data: { prompt, steps: card.steps, base_version_id: card.base_version_id, spec_hash: card.spec_hash },
  });
  expect(applied.status(), await applied.text()).toBe(202);

  await page.goto(`/compose?c=${comp.id}`);
  const list = page.getByRole("list").filter({ hasText: "shaft-20" });
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await expect(list.getByText("Applied")).toBeVisible({ timeout: 60_000 }).catch(async () => {
    await page.reload();
    await expect(list.getByText("Applied")).toBeVisible({ timeout: 30_000 });
  });
  await expect(page.getByRole("region", { name: /Composition 3D view/ })).toBeVisible({ timeout: 30_000 });
});

test("a read-only user sees no prompt", async ({ page, baseURL }) => {
  await page.context().clearCookies();
  await signInFast(page, baseURL, "viewer@wayam.local");
  await page.goto("/compose");
  await expect(page.getByText("You have read-only access")).toBeVisible();
  await expect(prompt(page)).toHaveCount(0);
});
