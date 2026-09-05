import { expect, test } from "@playwright/test";
import { apiAll } from "../lib/api";

test("selectors load all pages without dropping filters or following internal API hosts", async () => {
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];
  try {
    globalThis.fetch = async (input) => {
      const url = String(input);
      requests.push(url);
      const page = new URL(url, "http://local.test").searchParams.get("page");
      return Response.json({ results: [{ id: Number(page) }], next: page === "1" ? "http://api:8000/api/indents/?page=2" : null });
    };
    expect(await apiAll<{ id: number }>("/indents/?status=OPEN")).toEqual([{ id: 1 }, { id: 2 }]);
    expect(requests).toEqual([
      "/api/indents/?status=OPEN&page_size=200&page=1",
      "/api/indents/?status=OPEN&page_size=200&page=2",
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("reports expose the next page instead of hiding rows after the first 50", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    let json: unknown = [];
    if (url.pathname === "/api/auth/me/") json = { id: 1, username: "admin", role: "ADMIN" };
    if (url.pathname === "/api/reports/") json = [{ slug: "approved-unpaid", name: "Approved but unpaid" }];
    if (url.pathname === "/api/reports/approved-unpaid/") json = {
      slug: "approved-unpaid", name: "Approved but unpaid", count: 51, columns: ["trip"],
      rows: [{ trip: url.searchParams.get("page") === "2" ? "LAST-TRIP" : "FIRST-TRIP" }], totals: {},
    };
    await route.fulfill({ json });
  });
  await page.goto("/reports");
  await expect(page.getByText("FIRST-TRIP", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("LAST-TRIP", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
});
