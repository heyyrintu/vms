import { expect, test } from "@playwright/test";

test("finance can record TDS-only allocations with zero net cash", async ({ page }) => {
  const requests: Array<{ allocations: unknown }> = [];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = [];
    if (path === "/api/auth/me/") json = { id: 1, username: "finance", role: "FINANCE" };
    if (path === "/api/auth/csrf/") json = { csrfToken: "test-token" };
    if (path === "/api/finance/pending/")
      json = [
        {
          vendor_id: 1,
          vendor_name: "Test vendor",
          vendor_code: "V1",
          vendor_documents: [],
          total_net: "0.00",
          bank_accounts: [
            {
              id: 1,
              active: true,
              bank_name: "Test bank",
              masked_account_number: "****1234",
              ifsc_code: "TEST0000001",
            },
          ],
          items: [
            {
              approval_item_id: 1,
              approval_id: 1,
              approval_no: "PA-1",
              trip_no: "TEST-TRIP",
              remaining_gross: "25.00",
              remaining_tds: "25.00",
              remaining_net: "0.00",
              driver_documents: [],
              trip_documents: [],
            },
          ],
        },
      ];
    if (path === "/api/payments/") {
      requests.push(route.request().postDataJSON());
      await route.fulfill({ status: 400, json: { detail: "Test allocation received" } });
      return;
    }
    await route.fulfill({ json });
  });
  await page.goto("/finance");
  await page.getByRole("checkbox").check();
  await expect(page.getByLabel("Cash for TEST-TRIP")).toHaveValue("0.00");
  await expect(page.getByLabel("TDS for TEST-TRIP")).toHaveValue("25.00");
  await page.getByPlaceholder("Enter confirmed reference").fill("TDS-REFERENCE");
  await page.getByRole("button", { name: "Record paid transaction" }).click();
  await expect(page.getByText("Test allocation received")).toBeVisible();
  expect(requests[0].allocations).toEqual([
    { approval_item_id: 1, gross_amount_allocated: "25.00", tds_allocated: "25.00", net_cash_allocated: "0.00" },
  ]);
});
