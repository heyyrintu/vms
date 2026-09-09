import { expect, test } from "@playwright/test";

const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

function documentRow(id: number, kind: string, name: string) {
  return {
    id,
    kind,
    original_name: name,
    scan_status: "CLEAN",
    content_type: "image/png",
    size: PNG.length,
    download_url: `/api/documents/${id}/download/`,
    preview_url: `/api/documents/${id}/preview/`,
  };
}

// The finance evidence pack is one deck: vendor KYC, the cancelled cheque and
// every trip/driver document, so a payout can be checked without closing the viewer.
test("finance pages through a payout's whole evidence pack in the viewer", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/preview/")) {
      await route.fulfill({ status: 200, contentType: "image/png", body: PNG });
      return;
    }
    let json: unknown = [];
    if (path === "/api/auth/me/") json = { id: 1, username: "finance", role: "FINANCE" };
    if (path === "/api/auth/csrf/") json = { csrfToken: "test-token" };
    if (path === "/api/finance/pending/")
      json = [
        {
          vendor_id: 1,
          vendor_name: "Test vendor",
          vendor_code: "V1",
          vendor_legal_name: "Test Vendor Pvt Ltd",
          vendor_documents: [documentRow(1, "PAN", "vendor-pan.png")],
          total_net: "100.00",
          bank_accounts: [
            {
              id: 1,
              active: true,
              bank_name: "Test bank",
              masked_account_number: "****1234",
              ifsc_code: "TEST0000001",
              cancelled_cheque_documents: [documentRow(2, "CANCELLED_CHEQUE", "cheque.png")],
            },
          ],
          items: [
            {
              approval_item_id: 1,
              approval_id: 1,
              approval_no: "PA-1",
              trip_no: "TEST-TRIP",
              remaining_gross: "100.00",
              remaining_tds: "0.00",
              remaining_net: "100.00",
              trip_documents: [documentRow(3, "POD", "pod.png")],
              driver_documents: [documentRow(4, "DRIVING_LICENSE", "licence.png")],
            },
          ],
        },
      ];
    await route.fulfill({ json });
  });
  await page.goto("/finance");

  await page.getByRole("button", { name: "PAN · vendor-pan.png" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(page.getByTestId("doc-viewer-counter")).toHaveText("1 of 4");

  // Arrowing forward walks the deck, not just the list the file was clicked in.
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("doc-viewer-counter")).toHaveText("2 of 4");
  await expect(dialog).toContainText("cheque.png");
  await page.getByRole("button", { name: "Next document" }).click();
  await expect(page.getByTestId("doc-viewer-counter")).toHaveText("3 of 4");
  await expect(dialog).toContainText("pod.png");

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);

  // Opening from a trip document starts the same deck at that document.
  await page.getByRole("button", { name: "DRIVING LICENSE · licence.png" }).click();
  await expect(page.getByTestId("doc-viewer-counter")).toHaveText("4 of 4");
  await page.getByRole("button", { name: "Close document viewer" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
