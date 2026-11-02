import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

test("the form is prefilled with the dev engineer and Continue signs in", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByLabel("Work email")).toHaveValue("dev@wayam.local");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/home$/);
});

test("an unknown email shows an inline error and stays on sign-in", async ({ page }) => {
  await page.goto("/login");
  const email = page.getByLabel("Work email");
  await email.fill("nobody@example.org");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText(/No local account for that email/)).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
  // The error names the accounts that do exist, and clears when the field is edited.
  await expect(page.getByText(/dev@wayam\.local.*viewer@wayam\.local.*other@example\.com/)).toBeVisible();
  await email.fill("dev@wayam.local");
  await expect(page.getByText(/No local account for that email/)).toHaveCount(0);
});

test("email matching ignores case and surrounding spaces", async ({ page }) => {
  await signIn(page, "  Dev@Wayam.Local ");
});

test("SSO is shown as planned and cannot be used", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("button", { name: /Sign in with Microsoft/ })).toBeDisabled();
});

test("there is no theme toggle any more", async ({ page }) => {
  await signIn(page);
  await expect(page.getByRole("button", { name: /Switch to (dark|light)/ })).toHaveCount(0);
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.+/);
});

test("the rail lists the new navigation and marks planned items", async ({ page }) => {
  await signIn(page);
  const nav = page.getByRole("complementary", { name: "Sidebar" }).getByRole("navigation", { name: "Primary" });
  for (const name of ["Home", "Library", "Compose", "Projects"]) {
    await expect(nav.getByRole("link", { name })).toBeVisible();
  }
  await expect(nav).toContainText("Planned");
  await expect(nav.getByRole("link", { name: "Projects" })).toHaveAttribute("aria-current", "page");
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page).toHaveURL(/\/system$/);
});
