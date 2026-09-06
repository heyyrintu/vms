import { expect, type Page } from "@playwright/test";

// Signs in through the real login form against the seeded demo backend.
export async function loginAs(page: Page, username: string) {
  await page.context().clearCookies();
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill("ChangeMe123!");
  const [response] = await Promise.all([
    page.waitForResponse((value) => value.url().includes("/api/auth/login/")),
    page.getByRole("button", { name: "Sign in securely" }).click(),
  ]);
  expect(response.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Operations overview" })).toBeVisible();
}
