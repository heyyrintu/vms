import { expect, test } from "@playwright/test";

// The API is mocked here on purpose. A real end-to-end run would need to read a
// live one-time code, and the only ways to expose one are a test-only endpoint
// or a mailbox reader — the first is an authentication backdoor shipped in the
// codebase, the second is out of scope. Cryptographic and flow correctness are
// covered by apps/api/tests/test_otp_endpoints.py, which decrypts the outbound
// payload directly. What is left to prove here is the UI state machine.
const challenge = {
  challenge_id: "11111111-1111-4111-8111-111111111111",
  channel: "WHATSAPP",
  destination_masked: "+91 98****1111",
  expires_in: 300,
};

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

// lib/api.ts fetches a CSRF token before every unsafe request. Stubbing it keeps
// these specs runnable without the Django API, since everything else is mocked.
async function stubApi(page: import("@playwright/test").Page) {
  await page.context().clearCookies();
  await page.route("**/api/auth/csrf/", (route) => route.fulfill(json({ csrfToken: "test-token" })));
}

test("otp sign-in walks from identifier to code to authenticator", async ({ page }) => {
  await stubApi(page);
  await page.route("**/api/auth/otp/request/", (route) => route.fulfill(json(challenge)));
  await page.route("**/api/auth/otp/verify/", (route) =>
    route.fulfill(json({ detail: "A valid authenticator code is required", mfa_required: true }, 400)),
  );

  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in with a code instead" }).click();
  await page.getByLabel("Email or WhatsApp number").fill("919811111111");
  await page.getByRole("button", { name: "Send code" }).click();

  // The masked destination proves the request response drove the step change.
  await expect(page.getByText("+91 98****1111")).toBeVisible();
  await expect(page.getByRole("button", { name: /Resend code in \d+s/ })).toBeDisabled();

  await page.getByLabel("Verification code").fill("123456");
  await page.getByRole("button", { name: "Verify and sign in" }).click();

  // mfa_required in the error body must reveal the authenticator field rather
  // than stranding the user on a generic failure.
  await expect(page.getByLabel("Authenticator code")).toBeVisible();
});

test("a wrong code surfaces an error without advancing the step", async ({ page }) => {
  await stubApi(page);
  await page.route("**/api/auth/otp/request/", (route) => route.fulfill(json(challenge)));
  await page.route("**/api/auth/otp/verify/", (route) =>
    route.fulfill(json({ detail: "Invalid or expired code" }, 400)),
  );

  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in with a code instead" }).click();
  await page.getByLabel("Email or WhatsApp number").fill("919811111111");
  await page.getByRole("button", { name: "Send code" }).click();
  await page.getByLabel("Verification code").fill("000000");
  await page.getByRole("button", { name: "Verify and sign in" }).click();

  await expect(page.getByText("Invalid or expired code")).toBeVisible();
  await expect(page.getByLabel("Verification code")).toBeVisible();
  await expect(page.getByLabel("Authenticator code")).toBeHidden();
});

test("forgot password asks for an identifier then a code", async ({ page }) => {
  await stubApi(page);
  await page.route("**/api/auth/otp/request/", (route) => route.fulfill(json(challenge)));

  await page.goto("/login");
  await page.getByRole("button", { name: "Forgot password?" }).click();
  await page.getByLabel("Email or WhatsApp number").fill("member@drona.test");
  await page.getByRole("button", { name: "Send code" }).click();

  await expect(page.getByLabel("Verification code")).toBeVisible();
});

test("a verified recovery code reveals the new-password field", async ({ page }) => {
  await stubApi(page);
  await page.route("**/api/auth/otp/request/", (route) => route.fulfill(json(challenge)));
  await page.route("**/api/auth/otp/verify/", (route) => route.fulfill(json({ reset_ticket: "signed:ticket:value" })));

  await page.goto("/login");
  await page.getByRole("button", { name: "Forgot password?" }).click();
  await page.getByLabel("Email or WhatsApp number").fill("member@drona.test");
  await page.getByRole("button", { name: "Send code" }).click();
  await page.getByLabel("Verification code").fill("123456");
  await page.getByRole("button", { name: "Verify code" }).click();

  await expect(page.getByLabel("New password")).toBeVisible();
  await expect(page.getByRole("button", { name: "Reset password" })).toBeVisible();
});

test("the password form still exposes the selectors the other specs rely on", async ({ page }) => {
  // e2e/helpers.ts:loginAs drives these three names. Splitting the login page
  // into components could rename them silently, so pin them here where a break
  // is a clear failure rather than a confusing cascade across every other spec.
  await stubApi(page);
  await page.goto("/login");

  await expect(page.getByLabel("Username")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in securely" })).toBeVisible();
});
