# Code audit — 5 September 2026

## Follow-up: five lifecycle fixes

- Delivery now stores JSON-safe audit values and commits the trip, audit and queued notification together. Repeating delivery preserves its original timestamp.
- Submission and approval decisions reject cancelled/settled trips. Finance hides these trips and the payment service rejects new payments against them. Existing approval history is retained.
- Returned approvals must use the revision builder; the old snapshot cannot be resubmitted after editing the trip. A new revision captures current values and preserves history.
- Finance includes outstanding gross/TDS even when outstanding cash is zero. Payment completion checks gross, not cash alone, and the UI displays cash and TDS separately.
- Advance payment and reversal updates preserve dispatch/delivery/settlement lifecycle statuses. Reversals lock trip rows before updating their state.

These are code fixes, not a production data repair. Existing records affected before deployment require a separate review; no live records were modified.

## Fixed in this review

- Django model/password-policy validation errors escaped the API handler as HTTP 500. They now return structured HTTP 400 responses.
- Re-running MFA setup disabled an enabled authenticator. Setup now requires disabling the existing authenticator through the password-and-code flow first.
- Approval creation silently dropped missing trip IDs and collapsed duplicate IDs. Both cases now reject the entire request.
- Standard API pagination ignored the frontend's `page_size`, breaking register navigation. Page size is now supported and capped at 200.
- New-trip selectors and the approval builder loaded only the first page. They now load every page while preserving filters.
- Report screens had no navigation beyond the first 50 rows. Previous/Next controls are now available and reset when filters change.
- MIS XLSX and report CSV/XLSX download parameters conflicted with DRF renderer selection, causing HTTP 404. Export format now reaches the export handler.
- Ordinary trip edits could assign financial statuses such as ADVANCE_PAID without a payment record. Financial transitions must now use the appropriate workflow; supported dispatch transitions remain available.
- Trip advance percentages outside 0–100 were accepted and broke later calculations. They are now rejected at the API boundary.
- Settlement PATCH bypassed decimal validation. Invalid amounts now produce field errors and preserve the existing settlement.
- Duplicate payment allocations were caught too late during posting. They are now rejected before creating the payment.
- New-trip creation and unloading charges were separate requests, allowing partial creation and duplicate trips on retry. Initial unloading is now saved with the trip in one database transaction.
- Fixed an existing test import-order failure in the backend CI lint check.

## Verification

- Full backend suite: 95 passed, 1 PostgreSQL-only test skipped on SQLite. Lifecycle/integrity tests were also rerun after reversal locking changes: 22 passed.
- Targeted frontend tests: 8 passed (approval recovery, error messages, pagination, report navigation and TDS-only allocations). Browser API responses were mocked; these tests do not submit real approvals or payments.
- Backend Ruff, Django system checks, API schema validation and migration consistency checks passed.
- Frontend ESLint, TypeScript and optimized production build passed.
- No database migrations required.

## Limits and deployment

This is a code review and regression-test pass, not a guarantee that the whole application is bug-free. Authentication, trip/approval/payment/settlement flows, imports, integrations, reporting, Dockerfiles and CI configuration were inspected to varying depths. Existing backend tests cover imports, notifications and financial workflows; the full seeded browser smoke suite was not rerun against live services.

Docker Desktop was unavailable, so container builds/startup and PostgreSQL concurrency were not verified locally. Production Coolify logs, the production database, actual SMTP delivery and Meta WhatsApp delivery were not accessed. The unspecified current production error cannot be attributed to a particular fix without its response body or logs.

Changes are local. Commit and push them, then redeploy the VMS Compose application in Coolify. Deploy API and web changes together because new-trip creation now sends `unloading_advance` to the API. Preserve all persistent volumes. Verify a new trip with an unloading charge, approval submission, report pagination, and MIS/report exports after deployment.
