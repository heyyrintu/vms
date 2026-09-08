# API

Interactive documentation is served at `/api/docs/`; the generated OpenAPI document is `apps/api/schema.yml`.

Primary endpoints:

- Authentication: `/api/auth/csrf/`, `/login/`, `/logout/`, `/me/`, `/password/change/`, `/password/reset/confirm/`, `/otp/request/`, `/otp/verify/`, `/mfa/setup/`, `/mfa/confirm/`, `/mfa/disable/`
- Administration: `/api/users/`, `/api/settings/`, `/api/permission-matrix/`, `/api/approval-rules/`
- Masters and operations: `/api/clients/`, `/api/vendors/`, `/api/vendor-contacts/`, `/api/vendor-bank-accounts/`, `/api/vehicles/`, `/api/drivers/`, `/api/indents/`, `/api/trips/`
- Trip actions: `/api/trips/{id}/calculate/`, `/charges/`, `/revise/`, `/deliver/`, `/cancel/`
- Approvals: `/api/approval-batches/`, `/submit/`, `/decide/`, `/comments/`, plus `/api/comments/`, `/api/comments/mention-candidates/` and `/api/documents/`
- Finance: `/api/finance/pending/`, `/api/payments/`, `/api/payments/{id}/reverse/`, `/api/tds/`
- Settlement: `/api/settlements/`, `/submit/`, `/finalize/`, `/api/billings/`, `/api/recoveries/`
- Ledgers/search: `/api/vendor-ledger/{vendor_id}/`, `/api/trip-ledger/{trip_id}/`, `/api/dashboard/`, `/api/search/`
- Reports/imports: `/api/reports/`, `/api/reports/{slug}/`, `/api/imports/excel/preview/`, `/{job_id}/confirm/`, `/export/`
- MIS/history: `/api/mis/records/`, `/api/mis/template/`, `/api/mis/imports/`, `/api/mis/import/preview/`, `/api/mis/import/{job_id}/confirm/`
- Notifications/integrations: `/api/messages/`, `/api/notification-templates/`, `/api/notification-preferences/`, `/api/integration-connections/`, `/api/unmapped-messages/`
- Webhooks: `/api/webhooks/email/`, `/api/webhooks/whatsapp/`

Unsafe requests require the `X-CSRFToken` header. All non-webhook endpoints except health/readiness/CSRF/login require an authenticated session. Role and object authorization are applied server-side.

One-time codes are an alternative to password sign-in and the only route to password recovery. `POST /api/auth/otp/request/` takes `{identifier, purpose}`, where `identifier` is an email address or a WhatsApp number and `purpose` is `LOGIN` or `PASSWORD_RESET`; the identifier's shape selects the channel. It answers `{challenge_id, channel, destination_masked, expires_in}`, and an unknown identifier gets the same shape and status with a fabricated `challenge_id`, so a casual caller cannot tell the two apart. That is deliberate but not airtight: a known account's `destination_masked` is derived from the stored email while an unknown one is derived from the submitted text, so submitted casing survives only in the latter, and the per-user resend limit answers 429 for a known account where an unknown one still answers 200. Treat the endpoint as raising the cost of account discovery, not preventing it. `POST /api/auth/otp/verify/` takes `{challenge_id, code, purpose}` and returns a session for `LOGIN` or `{reset_ticket}` for `PASSWORD_RESET`. A user with MFA enabled must also send `otp`, the authenticator code — a delivered code never substitutes for the second factor. Codes expire in five minutes, allow five attempts, and are single-use; requesting a new one invalidates the previous. `POST /api/auth/password/reset/confirm/` now takes `{reset_ticket, new_password}`.

`/api/auth/password/reset/` was removed along with the emailed reset link it produced; `uid` and `token` are no longer accepted by the confirm endpoint. Because `email` and `whatsapp_phone` must resolve to exactly one account, both are uniquely constrained across all users; run `python manage.py check_login_identifiers` before migrating an existing database to list any conflicts.

Files are returned only through authenticated `/api/documents/{id}/download/` actions; the object store is not exposed as a public media directory in production. Built-in page-number pagination defaults to 50 rows. Report endpoints additionally accept `date_from`, `date_to`, `vendor`, `client`, `branch`, `page_size`, and `format=csv|xlsx`.

Operational registers support server-side pagination and filters. Trips accept `search`, `status`, `vendor`, `client`, `branch`, `vehicle_type`, `date_from`, and `date_to`; indents accept `search`, `status`, `client`, `assigned`, `branch`, `date_from`, and `date_to`; approval batches accept `search`, `status`, `requester`, `client`, `date_from`, and `date_to`; payments accept `search`, `status`, `vendor`, `date_from`, and `date_to`.

Vendor and driver verification files use the same protected document endpoint. Supported combinations are `vendor` with `AADHAAR` or `PAN`, `driver` with `AADHAAR`, `PAN` or `DRIVING_LICENSE`, and `vendor_bank_account` with `CANCELLED_CHEQUE`. Vendor account numbers are write-only, encrypted at rest and returned only as a last-four mask; IFSC values are normalized and validated.

MIS record queries accept `q`, `date_from`, `date_to`, `vendor`, `status`, `payment_status=UNPAID|PARTIAL|PAID`, `page`, `page_size`, and `format=xlsx`. All authenticated trip readers may use the register; transporter results remain vendor-scoped. MIS history preview and confirmation are restricted to administrators.
