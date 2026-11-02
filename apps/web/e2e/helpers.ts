import { expect, type Page } from "@playwright/test";

/** Seeded dev identities (apps/web/src/lib/session.ts). */
export const DEV = "dev@wayam.local";

/** Sign in through the real form: Work email + Continue. */
export async function signIn(page: Page, email = DEV) {
  await page.goto("/login");
  await page.getByLabel("Work email").fill(email);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/projects$/);
}

/** Skip the form for tests that are not about sign-in: set the session cookie directly. */
export async function signInFast(page: Page, baseURL: string | undefined, email = DEV) {
  await page.context().addCookies([{ name: "shilpa-session", value: encodeURIComponent(email), url: baseURL! }]);
}

/** Horizontal overflow of the page in px (<= 0 means none). */
export const overflowX = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
