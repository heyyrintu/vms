import { expect, test } from "@playwright/test";
import { createReadyTrip, loginAs } from "./helpers";

test("TDS register exposes vendor and date filters with pagination", async ({ page }) => {
  await loginAs(page, "finance");
  await page.goto("/tds");
  await expect(page.getByLabel("Transporter")).toBeVisible();
  await expect(page.getByLabel("From date")).toBeVisible();
  await page.getByLabel("From date").fill("2099-01-01");
  await expect(page.getByText("No posted TDS entries.")).toBeVisible();
});

test("trip register status filter lists every backend state", async ({ page }) => {
  await loginAs(page, "operations");
  await page.goto("/trips");
  await expect(page.getByLabel("Trip status")).toBeVisible();
  // The select is visible as soon as its "All statuses" placeholder renders, but
  // the states themselves arrive with the /api/choices query. allTextContents()
  // is a one-shot read, so assert through expect.poll rather than racing it.
  await expect
    .poll(() => page.getByLabel("Trip status").locator("option").allTextContents())
    .toContain("Settlement approval pending");
});

test("fleet page loads driver documents on demand only", async ({ page }) => {
  const documentRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/documents/")) documentRequests.push(request.url());
  });
  await loginAs(page, "operations");
  await page.goto("/fleet");
  await expect(page.getByRole("heading", { name: "Driver master" })).toBeVisible();
  expect(documentRequests.filter((url) => url.includes("page_size=500"))).toHaveLength(0);
});

test("operations builds an approval, approver approves, finance pays", async ({ page }) => {
  await loginAs(page, "operations");
  const created = await createReadyTrip(page);
  await page.goto("/approvals/new");
  const row = page.locator("tbody tr", { hasText: created.trip_no }).first();
  await expect(row).toBeVisible();
  await row.locator("input[type=checkbox]").check();
  await page.getByRole("button", { name: "Create & submit approval" }).click();
  await expect(page).toHaveURL(/\/approvals\/\d+/);
  const approvalUrl = page.url();

  await loginAs(page, "approver");
  await page.goto(approvalUrl);
  await page.getByRole("button", { name: /^Approve/ }).click();
  await expect(page.getByText("APPROVED").first()).toBeVisible();

  await loginAs(page, "finance");
  await page.goto("/finance");
  const line = page.locator("tr", { hasText: created.trip_no }).first();
  await expect(line).toBeVisible();
  await line.locator("input[type=checkbox]").check();
  await page.getByLabel("UTR / bank reference").fill(`E2E-${Date.now()}`);
  await page.getByRole("button", { name: "Record paid transaction" }).click();
  await expect(page).toHaveURL(/\/payments\/\d+/);
  await expect(page.getByText("PAID").first()).toBeVisible();
});
