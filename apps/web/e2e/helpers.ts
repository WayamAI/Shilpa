import { expect, type Page } from "@playwright/test";
import type { Locator } from "@playwright/test";

/** Seeded dev identities (apps/web/src/lib/session.ts). */
export const DEV = "dev@wayam.local";

/** Sign in through the real form: Work email + Continue. */
export async function signIn(page: Page, email = DEV) {
  await page.goto("/login");
  await page.getByLabel("Work email").fill(email);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/home$/);
  /* Most specs start from the projects list. */
  await page.goto("/projects");
}

/** Skip the form for tests that are not about sign-in: set the session cookie directly. */
export async function signInFast(page: Page, baseURL: string | undefined, email = DEV) {
  await page.context().addCookies([{ name: "shilpa-session", value: encodeURIComponent(email), url: baseURL! }]);
}

/** Horizontal overflow of the page in px (<= 0 means none). */
export const overflowX = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

/** Pick an option by value from the custom Select (role=combobox + listbox). */
export async function pickOption(combobox: Locator, value: string) {
  await combobox.click();
  await combobox.page().locator(`[role="option"][data-value="${value}"]`).click();
}
