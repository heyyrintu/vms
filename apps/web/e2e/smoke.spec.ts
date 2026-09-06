import { expect, test } from "@playwright/test";

async function loginAs(page: import("@playwright/test").Page, username: string) {
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

async function apiCall<T>(
  page: import("@playwright/test").Page,
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const result = await page.evaluate(
    async ({ path, method, body }) => {
      const csrf = decodeURIComponent(
        document.cookie
          .split("; ")
          .find((part) => part.startsWith("csrftoken="))
          ?.split("=")[1] ?? "",
      );
      const response = await fetch(path, {
        method,
        credentials: "include",
        headers: { "Content-Type": "application/json", ...(csrf ? { "X-CSRFToken": csrf } : {}) },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      return { ok: response.ok, status: response.status, data };
    },
    { path, method, body },
  );
  expect(result.ok, JSON.stringify(result.data)).toBeTruthy();
  return result.data as T;
}

test("operations user can sign in and open the trip register", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByAltText("Drona Logitech")).toBeVisible();
  await expect(page).toHaveTitle(/Drona Logitech/);
  await page.getByLabel("Username").fill("operations");
  await page.getByLabel("Password").fill("ChangeMe123!");
  await page.getByRole("button", { name: "Sign in securely" }).click();

  await expect(page.getByRole("heading", { name: "Operations overview" })).toBeVisible();
  await expect(page.getByText("Pending approvals", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Trip register" }).click();
  await expect(page.getByRole("heading", { name: "Trip register" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Freight (100%)" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Freight balance" })).toBeVisible();
});

test("transporter cannot access the internal finance queue", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill("transporter");
  await page.getByLabel("Password").fill("ChangeMe123!");
  await page.getByRole("button", { name: "Sign in securely" }).click();
  await expect(page.getByRole("heading", { name: "Operations overview" })).toBeVisible();

  const response = await page.request.get("/api/finance/pending/");
  expect(response.status()).toBe(403);
});

test("administrator can open SMTP integration settings", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("ChangeMe123!");
  await page.getByRole("button", { name: "Sign in securely" }).click();
  await expect(page.getByRole("heading", { name: "Operations overview" })).toBeVisible();

  await page.goto("/integrations");
  await expect(page.getByRole("heading", { name: "SMTP email" })).toBeVisible();
  await expect(page.getByLabel("SMTP host")).toBeVisible();
  await expect(page.getByLabel("From email")).toBeVisible();
  await expect(page.getByText("Gmail OAuth")).toHaveCount(0);
});

test("approval deep link returns the approver to the requested approval after login", async ({ page }) => {
  await page.goto("/approvals/1");
  await expect(page).toHaveURL(/\/login\?next=/);
  await page.getByLabel("Username").fill("approver");
  await page.getByLabel("Password").fill("ChangeMe123!");
  await page.getByRole("button", { name: "Sign in securely" }).click();

  await expect(page).toHaveURL(/\/approvals\/1$/);
  await expect(page.locator("h1")).toContainText("PA-");
});

test("operations onboarding forms expose vendor bank and driver KYC fields", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill("operations");
  await page.getByLabel("Password").fill("ChangeMe123!");
  await page.getByRole("button", { name: "Sign in securely" }).click();
  await expect(page.getByRole("heading", { name: "Operations overview" })).toBeVisible();

  await page.goto("/vendors");
  await page.getByRole("button", { name: "+ New vendor" }).click();
  await expect(page.getByLabel("Account number")).toBeVisible();
  await expect(page.getByLabel("IFSC code")).toBeVisible();
  await expect(page.getByLabel("Cancelled cheque proof")).toBeVisible();
  await expect(page.getByLabel("Aadhaar document")).toBeVisible();

  await page.goto("/fleet");
  await expect(page.getByRole("heading", { name: "Add driver" })).toBeVisible();
  await expect(page.getByLabel("Driving licence")).toBeVisible();
  await expect(page.getByLabel("PAN document")).toBeVisible();
});

test("operations can access indent registration, Excel upload and multi-indent trip selection", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill(process.env.E2E_OPERATIONS_USER ?? "operations");
  await page.getByLabel("Password").fill(process.env.E2E_OPERATIONS_PASSWORD ?? "ChangeMe123!");
  await page.getByRole("button", { name: "Sign in securely" }).click();
  await expect(page.getByRole("heading", { name: "Operations overview" })).toBeVisible();

  await page.goto("/indents");
  await expect(page.getByRole("heading", { name: "Indent register" })).toBeVisible();
  await page.getByRole("button", { name: "+ Register indent" }).click();
  await expect(page.getByLabel("Challan no.")).toBeVisible();
  await expect(page.getByLabel("Challan date & time")).toBeVisible();
  await expect(page.getByLabel("Ship-to party code")).toBeVisible();
  await expect(page.getByLabel("Quantity (LTR)")).toBeVisible();
  await page.getByRole("button", { name: "Upload Excel" }).click();
  await expect(page.getByRole("link", { name: "Download sample format" })).toBeVisible();

  await page.goto("/trips/new");
  await expect(page.getByRole("heading", { name: "Select indents" })).toBeVisible();
  await expect(page.getByLabel("Find by challan, party or route")).toBeVisible();
});

test("administrator can search and upload MIS history", async ({ page }) => {
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("ChangeMe123!");
  const [loginResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().includes("/api/auth/login/")),
    page.getByRole("button", { name: "Sign in securely" }).click(),
  ]);
  expect(loginResponse.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Operations overview" })).toBeVisible();

  await page.goto("/mis");
  await expect(page.getByRole("heading", { name: "MIS & historical records" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "100% amount" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Total remaining" })).toBeVisible();
  await page.getByRole("button", { name: "+ Upload records" }).click();
  await expect(page.getByRole("heading", { name: "Post historical records" })).toBeVisible();
  await expect(page.getByLabel(/MIS history workbook/)).toBeVisible();
});

test("trip approval and partial finance payment complete across roles", async ({ page }) => {
  const suffix = Date.now().toString().slice(-8);
  await loginAs(page, "operations");
  const client = await apiCall<{ id: number }>(page, "/api/clients/", "POST", {
    code: `E2E${suffix}`,
    name: `E2E Client ${suffix}`,
    default_branch: "Sonipat",
    active: true,
  });
  const vendor = await apiCall<{ id: number }>(page, "/api/vendors/", "POST", {
    vendor_code: `E2EV${suffix}`,
    legal_name: `E2E Vendor ${suffix} Pvt Ltd`,
    display_name: `E2E Vendor ${suffix}`,
    status: "ACTIVE",
  });
  const vehicle = await apiCall<{ id: number }>(page, "/api/vehicles/", "POST", {
    registration_no: `HR10E${suffix}`,
    vendor: vendor.id,
    vehicle_type: "32 FT MXL",
    capacity: "25000",
  });
  const driver = await apiCall<{ id: number }>(page, "/api/drivers/", "POST", {
    name: `E2E Driver ${suffix}`,
    phone: `9199${suffix}`,
    vendor: vendor.id,
  });
  const today = new Date().toISOString().slice(0, 10);
  const indent = await apiCall<{ id: number }>(page, "/api/indents/", "POST", {
    client: client.id,
    indent_no: `E2E-IND-${suffix}`,
    challan_no: `E2E-IND-${suffix}`,
    indent_date: today,
    origin: "Sonipat",
    destination: "Delhi",
    branch: "Sonipat",
    status: "OPEN",
  });
  const trip = await apiCall<{ id: number }>(page, "/api/trips/", "POST", {
    indent: indent.id,
    indent_ids: [indent.id],
    client: client.id,
    origin: "Sonipat",
    destination: "Delhi",
    deployment_date: today,
    vendor: vendor.id,
    vehicle: vehicle.id,
    driver: driver.id,
    vendor_freight_rate: "50000.00",
    advance_percent: "90.00",
    branch: "Sonipat",
  });
  const batch = await apiCall<{ id: number }>(page, "/api/approval-batches/", "POST", {
    trip_ids: [trip.id],
    purpose: "ADVANCE",
  });
  await apiCall(page, `/api/approval-batches/${batch.id}/submit/`, "POST", {});

  await loginAs(page, "approver");
  const approved = await apiCall<{ status: string }>(page, `/api/approval-batches/${batch.id}/decide/`, "POST", {
    decision: "APPROVE",
    comment: "E2E approval",
  });
  expect(approved.status).toBe("APPROVED");

  await loginAs(page, "finance");
  const pending = await apiCall<
    Array<{
      vendor_id: number;
      items: Array<{ approval_item_id: number; trip_id: number; remaining_tds: string; remaining_net: string }>;
    }>
  >(page, "/api/finance/pending/");
  const line = pending.find((group) => group.vendor_id === vendor.id)!.items.find((item) => item.trip_id === trip.id)!;
  const tds = (Number(line.remaining_tds) / 2).toFixed(2);
  const net = (Number(line.remaining_net) / 2).toFixed(2);
  await apiCall(page, "/api/payments/", "POST", {
    vendor: vendor.id,
    payment_date: today,
    payment_mode: "BANK_TRANSFER",
    utr_reference: `E2E-UTR-${suffix}`,
    allocations: [
      {
        approval_item_id: line.approval_item_id,
        gross_amount_allocated: (Number(tds) + Number(net)).toFixed(2),
        tds_allocated: tds,
        net_cash_allocated: net,
      },
    ],
  });
  const ledger = await apiCall<{ cash_paid: string; remaining_to_pay: string }>(page, `/api/trip-ledger/${trip.id}/`);
  expect(Number(ledger.cash_paid)).toBeGreaterThan(0);
  expect(Number(ledger.remaining_to_pay)).toBeGreaterThan(0);

  await page.goto("/finance");
  await expect(page.getByRole("heading", { name: "Finance review & pending payments" })).toBeVisible();
  await expect(page.getByText(`E2E Vendor ${suffix}`, { exact: true })).toBeVisible();
});
