import { expect, test, type Page } from "@playwright/test";
import { ApiError } from "../lib/api";

const trip = {
  id: 1,
  trip_no: "TEST-001",
  deployment_date: "2026-09-05",
  origin: "Sonipat",
  destination: "Delhi",
  vendor_name: "Test vendor",
  vehicle_no: "TEST123",
  vendor_freight_rate: "5000.00",
  advance_percent: "90.00",
  calculation: { gross_requested: "6000.00", tds_this_payment: "45.00", net_requested: "5955.00" },
};

async function mockWorkspace(page: Page, activeApproval: unknown = null) {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = [];
    if (path === "/api/auth/me/") json = { id: 1, username: "operations", role: "OPERATIONS" };
    if (path === "/api/auth/csrf/") json = { csrfToken: "test-token" };
    if (path === "/api/trips/") json = { count: 1, results: [{ ...trip, active_approval: activeApproval }] };
    await route.fulfill({ json });
  });
}

test("API errors expose field, list and non-field validation messages", () => {
  expect(new ApiError(400, { advance_percent: ["Enter a valid number."] }).message).toBe(
    "advance percent: Enter a valid number.",
  );
  expect(new ApiError(400, ["Financial fields are locked"]).message).toBe("Financial fields are locked");
  expect(new ApiError(400, { non_field_errors: ["Invalid combination"] }).message).toBe("Invalid combination");
  expect(new ApiError(400, { detail: "Not eligible" }).message).toBe("Not eligible");
  expect(new ApiError(502, {}).message).toBe("Request failed (502)");
});

test("unchanged trip goes directly to atomic create and submit without PATCH", async ({ page }) => {
  await mockWorkspace(page);
  const patches: unknown[] = [];
  await page.route("**/api/trips/1/", async (route) => {
    patches.push(route.request().postDataJSON());
    await route.fulfill({ status: 400, json: ["Snapshot locked"] });
  });
  let submitted: unknown;
  await page.route("**/api/approval-batches/", async (route) => {
    submitted = route.request().postDataJSON();
    await route.fulfill({ status: 400, json: { detail: "Submission test reached" } });
  });
  await page.goto("/approvals/new");
  await page.getByRole("checkbox").check();
  // Formatting-only edits must also avoid a financial write.
  await page.getByLabel("Freight for TEST-001").fill("5000");
  await page.getByRole("button", { name: "Create & submit approval" }).click();
  await expect(page.getByText("Submission test reached")).toBeVisible();
  expect(patches).toEqual([]);
  expect(submitted).toEqual({ trip_ids: [1], submit: true });
});

test("changed field is patched and validation failure stops submission", async ({ page }) => {
  await mockWorkspace(page);
  let patch: unknown;
  let submissions = 0;
  await page.route("**/api/trips/1/", async (route) => {
    patch = route.request().postDataJSON();
    await route.fulfill({
      status: 400,
      json: { vendor_freight_rate: ["Ensure this value is greater than or equal to 0."] },
    });
  });
  await page.route("**/api/approval-batches/", async (route) => {
    submissions++;
    await route.fulfill({ json: {} });
  });
  await page.goto("/approvals/new");
  await page.getByRole("checkbox").check();
  await page.getByLabel("Freight for TEST-001").fill("-1");
  await page.getByRole("button", { name: "Create & submit approval" }).click();
  await expect(page.getByText("vendor freight rate: Ensure this value is greater than or equal to 0.")).toBeVisible();
  expect(patch).toEqual({ vendor_freight_rate: "-1" });
  expect(submissions).toBe(0);
});

test("existing draft offers a recovery link instead of an eligible checkbox", async ({ page }) => {
  await mockWorkspace(page, { id: 7, approval_no: "PA-TEST-007", status: "DRAFT" });
  await page.goto("/approvals/new");
  await expect(page.getByRole("link", { name: "Open PA-TEST-007 (DRAFT)" })).toHaveAttribute("href", "/approvals/7");
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Create & submit approval" })).toBeDisabled();
});

test("requester can submit an existing draft from its detail page", async ({ page }) => {
  await mockWorkspace(page);
  const batch = {
    id: 7,
    approval_no: "PA-TEST-007",
    client_name: "Test client",
    purpose: "ADVANCE",
    revision_no: 1,
    status: "DRAFT",
    requested_by: 1,
    current_stage: 1,
    gross_requested: "6000.00",
    tds_requested: "45.00",
    net_requested: "5955.00",
    stage_decisions: [],
    approval_rule_snapshot: {},
    revision_diff: [],
    items: [],
    actions: [],
  };
  await page.route("**/api/approval-batches/7/", (route) => route.fulfill({ json: batch }));
  let submissions = 0;
  await page.route("**/api/approval-batches/7/submit/", async (route) => {
    expect(route.request().method()).toBe("POST");
    submissions++;
    await route.fulfill({ json: { ...batch, status: "PENDING" } });
  });
  await page.goto("/approvals/7");
  await page.getByRole("button", { name: "Submit draft approval" }).click();
  await expect(page.getByRole("button", { name: "Submit draft approval" })).toHaveCount(0);
  await expect(page.getByText("PENDING", { exact: true })).toBeVisible();
  expect(submissions).toBe(1);
});
