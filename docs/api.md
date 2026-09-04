# API

Interactive documentation is served at `/api/docs/`; the generated OpenAPI document is `apps/api/schema.yml`.

Primary endpoints:

- Authentication: `/api/auth/csrf/`, `/login/`, `/logout/`, `/me/`, `/password/change/`, `/password/reset/`, `/mfa/setup/`, `/mfa/confirm/`, `/mfa/disable/`
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

Files are returned only through authenticated `/api/documents/{id}/download/` actions; the object store is not exposed as a public media directory in production. Built-in page-number pagination defaults to 50 rows. Report endpoints additionally accept `date_from`, `date_to`, `vendor`, `client`, `branch`, `page_size`, and `format=csv|xlsx`.

Operational registers support server-side pagination and filters. Trips accept `search`, `status`, `vendor`, `client`, `branch`, `vehicle_type`, `date_from`, and `date_to`; indents accept `search`, `status`, `client`, `assigned`, `branch`, `date_from`, and `date_to`; approval batches accept `search`, `status`, `requester`, `client`, `date_from`, and `date_to`; payments accept `search`, `status`, `vendor`, `date_from`, and `date_to`.

Vendor and driver verification files use the same protected document endpoint. Supported combinations are `vendor` with `AADHAAR` or `PAN`, `driver` with `AADHAAR`, `PAN` or `DRIVING_LICENSE`, and `vendor_bank_account` with `CANCELLED_CHEQUE`. Vendor account numbers are write-only, encrypted at rest and returned only as a last-four mask; IFSC values are normalized and validated.

MIS record queries accept `q`, `date_from`, `date_to`, `vendor`, `status`, `payment_status=UNPAID|PARTIAL|PAID`, `page`, `page_size`, and `format=xlsx`. All authenticated trip readers may use the register; transporter results remain vendor-scoped. MIS history preview and confirmation are restricted to administrators.
