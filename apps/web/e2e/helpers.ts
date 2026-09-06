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

type Paged<T> = { results: T[] } | T[];

export async function apiCall<T>(page: Page, path: string, method = "GET", body?: unknown): Promise<T> {
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
  if (!result.ok) throw new Error(`${method} ${path} failed with ${result.status}: ${JSON.stringify(result.data)}`);
  return result.data as T;
}

function rows<T>(value: Paged<T>): T[] {
  return Array.isArray(value) ? value : value.results;
}

/** Creates a READY trip (and a vendor bank account if missing) so workflow tests never depend on leftover seed state. */
export async function createReadyTrip(page: Page): Promise<{ id: number; trip_no: string; vendor: number }> {
  const clients = rows(await apiCall<Paged<{ id: number }>>(page, "/api/clients/?page_size=1"));
  const vendors = rows(
    await apiCall<Paged<{ id: number; bank_accounts?: unknown[] }>>(page, "/api/vendors/?status=ACTIVE&page_size=50"),
  );
  const indents = rows(
    await apiCall<Paged<{ id: number; origin: string; destination: string }>>(page, "/api/indents/?page_size=1"),
  );
  let vendor: { id: number } | undefined;
  let vehicle: { id: number } | undefined;
  for (const candidate of vendors) {
    const vehicles = rows(
      await apiCall<Paged<{ id: number }>>(page, `/api/vehicles/?vendor=${candidate.id}&page_size=1`),
    );
    if (vehicles.length) {
      vendor = candidate;
      vehicle = vehicles[0];
      break;
    }
  }
  if (!vendor || !vehicle || !clients.length || !indents.length)
    throw new Error("Seed data lacks a client, vendor with vehicle, or indent");
  const drivers = rows(await apiCall<Paged<{ id: number }>>(page, `/api/drivers/?vendor=${vendor.id}&page_size=1`));
  const driver = drivers[0] ?? rows(await apiCall<Paged<{ id: number }>>(page, "/api/drivers/?page_size=1"))[0];
  const detail = await apiCall<{ bank_accounts?: unknown[] }>(page, `/api/vendors/${vendor.id}/`);
  if (!detail.bank_accounts?.length) {
    await apiCall(page, "/api/vendor-bank-accounts/", "POST", {
      vendor: vendor.id,
      bank_name: "E2E Bank",
      account_holder: "E2E Vendor",
      account_number: "123456789012",
      ifsc_code: "HDFC0001234",
    });
  }
  const indent = indents[0];
  const today = new Date().toISOString().slice(0, 10);
  const trip = await apiCall<{ id: number; trip_no: string }>(page, "/api/trips/", "POST", {
    indent: indent.id,
    indent_ids: [indent.id],
    client: clients[0].id,
    origin: indent.origin,
    destination: indent.destination,
    deployment_date: today,
    vendor: vendor.id,
    vehicle: vehicle.id,
    driver: driver.id,
    vendor_freight_rate: "50000.00",
    advance_percent: "90",
    unloading_advance: "0",
    uom_ltrs: "LTR",
    branch: "Sonipat",
  });
  return { id: trip.id, trip_no: trip.trip_no, vendor: vendor.id };
}
