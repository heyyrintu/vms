# Codex Build Prompt

You are the primary software implementation agent for a production-grade internal transport operations and vendor payment web application.

## Mission

Build the **NPL Transport Deployment, Vendor Advance & Payment Management System** described in `PRD.md`, following the implementation sequence in `PLAN.md`.

The existing business process uses an Excel payment approval sheet containing fields such as FROM, TO, DATE, UOM-LTRS, QTY, TOTAL LOAD, vehicle rate, unloading, 90% advance, total payment, transporter, vehicle number, driver name/phone, vehicle type, and EDD. The new app must preserve this workflow while adding structured approvals, 1% configurable TDS, finance payment tracking, vendor/trip ledgers, comments, audit history, Gmail, and WhatsApp integration.

Read `PRD.md` and `PLAN.md` completely before changing code. Treat `PRD.md` as the product source of truth. When the documents conflict, prioritize financial integrity, server-side authorization, auditability, and trip-wise traceability.

## Architecture

Use a modular monorepo:

```text
apps/api   - Django + Django REST Framework
apps/web   - Next.js + React + TypeScript
infra      - Docker/devops scripts
```

Use:
- PostgreSQL
- Redis
- Celery
- S3-compatible object storage
- Docker Compose for local development
- current stable compatible package versions; pin them in lockfiles

Frontend:
- Next.js
- TypeScript strict mode
- Tailwind CSS
- accessible component primitives such as shadcn/ui or equivalent
- TanStack Query or equivalent for server state

Backend:
- Django
- Django REST Framework
- pytest
- OpenAPI schema

Do not introduce microservices unless a concrete requirement demands them.

## Non-Negotiable Business Invariants

1. Every approved/payment amount must remain traceable to a trip.
2. One approval batch may contain multiple vendors.
3. A finance payment transaction belongs to exactly one vendor.
4. A finance payment may allocate to multiple approved trip items for that vendor.
5. Allocation totals must reconcile exactly to the payment transaction.
6. Approved financial values cannot be silently edited.
7. Material changes create a revision/re-approval requirement.
8. Paid transactions cannot be hard-deleted or silently rewritten; use reversal/adjustment.
9. All money uses Decimal/fixed precision, never float.
10. TDS rate defaults to 1.00% as requested but the taxable basis/policy must be configurable; do not hard-code tax-law assumptions.
11. Default advance percent is 90%, configurable.
12. TDS is withholding, not a reduction in vendor economic cost for profitability.
13. Transporters must never receive another vendor's data.
14. Internal comments must never leak to transporter notifications.
15. Server-side permissions are authoritative; hiding buttons is not security.
16. External integration events must be idempotent.
17. Payment/approval state transitions must be transactional and audited.

## Core Calculation Contract

Implement a dedicated calculation service with tests.

```text
freight_advance_gross = vendor_freight_rate * advance_percent

gross_requested = freight_advance_gross
                + advance_eligible_charges
                - advance_stage_deductions

tds_this_payment = resolve according to configured TDS policy
net_requested = gross_requested - tds_this_payment

final_vendor_gross_cost = final_freight
                        + additive_charges
                        - vendor_deductions

total_tds_required = configured TDS policy applied to final taxable base
net_vendor_payable_total = final_vendor_gross_cost - total_tds_required
remaining_cash_payable = net_vendor_payable_total - total_cash_paid
```

Return a calculation breakdown to the frontend so users always see base, rate, TDS, gross, and net.

## TDS Policy Modes

Implement:
- PER_PAYMENT_TAXABLE_AMOUNT
- FULL_FREIGHT_AT_FIRST_ADVANCE
- CUMULATIVE_TRIP_LIABILITY
- MANUAL_WITH_APPROVAL

Use organization/vendor policy resolution. Store the resolved policy snapshot on approval items so historical approvals do not change when settings change later.

## Required Roles

- Operations
- Approver
- Finance
- Management
- Transporter
- Admin

Build and test a clear permission matrix.

## Required Core Models

Implement models conceptually matching the PRD:

- Client
- Vendor
- VendorContact
- VendorBankAccount
- Vehicle
- Driver
- Indent
- Trip
- TripCharge
- PaymentApprovalBatch
- PaymentApprovalItem
- ApprovalAction
- Comment / Activity
- FinancePaymentTransaction
- PaymentAllocation
- TDSEntry
- FinalTripSettlement
- ClientBilling
- Document/Attachment
- IntegrationConnection
- IntegrationMessage
- AuditLog
- ApprovalRule / ApprovalStage
- OrganizationSettings

Use database constraints/indexes to protect invariants where possible.

## Required Initial Screens

Build polished, functional versions of:

1. Login
2. Dashboard
3. Trip Register
4. Trip Create/Edit/Detail
5. Vendor List/Detail
6. Payment Approval Builder
7. Approval Inbox
8. Approval Detail + Comments/Activity
9. Finance Pending Payments grouped by vendor
10. Payment Create/Detail
11. Vendor Ledger
12. Trip Ledger
13. Payment Register
14. TDS Register
15. Settings/Approval Matrix
16. Excel Import preview

Favor dense, clear business tables similar to a well-designed operational spreadsheet. Desktop-first, responsive on mobile.

## Approval UX

Approval detail must show:
- every trip line
- vendor subtotals
- gross/TDS/net totals
- attachments
- activity timeline
- revision history

Actions:
- Approve all
- Approve selected items
- Reject selected items
- Send back
- Comment / @mention

Reject/send-back requires a reason.

## Finance UX

When a batch is approved, do NOT simply create one payment for the batch.

Create a Finance queue that groups approved unpaid items by vendor. Finance may select multiple items for the same vendor, create one payment, enter payment date/bank/UTR/proof, and allocate the payment across the selected trips.

Prevent selecting items from different vendors into one payment transaction.

## Comments / Activity

Do not build a separate forum application. Build contextual threaded comments on Trip and Approval pages.

Support:
- @mentions
- attachments
- replies
- INTERNAL vs TRANSPORTER_VISIBLE
- system activity events
- audit trail

## Gmail Integration

Implement behind an adapter/service interface so local development can use a fake provider.

Production adapter:
- Google OAuth
- Gmail API send
- store Gmail message ID and thread ID
- mailbox watch via Gmail `users.watch` + Google Cloud Pub/Sub
- fetch mailbox history/messages after notifications
- map replies to approval/trip threads
- renew mailbox watch before expiration
- idempotent processing
- manual reconciliation queue for unmapped replies

Email subjects should include a stable approval/trip identifier.

## WhatsApp Integration

Implement behind an adapter/service interface with a fake/local provider.

Production adapter:
- official WhatsApp Business Cloud API
- outbound approved template messages where required
- inbound webhook messages
- sent/delivered/read/failed status tracking
- reply context mapping
- idempotency
- webhook verification

Transporter payloads must contain only that vendor's data.

## Legacy Excel Import

Support import of the current 17-column workbook structure:

```text
SR NO
FROM
TO
DATE
UOM-LTRS
QTY
TOTAL LOAD
RATES FOR VEHICLES
UNLOADING
ADVANCE
TOTAL PAYMENTS TO BE DONE
TRANSPORTER
VH NO
DRIVER NAME
DRIVER NO
VH TYPE
EDD
```

Legacy formulas are:

```text
ADVANCE = RATES FOR VEHICLES * 90%
TOTAL PAYMENTS TO BE DONE = ADVANCE + UNLOADING
```

Importer requirements:
- upload
- preview
- normalized mapping
- Excel serial date handling
- row validation
- duplicate warnings
- create missing vendor/vehicle option
- audit source import

Use synthetic fixtures in tests; never commit real driver phone numbers or bank data.

## Security

- Authentication tokens/session data only in secure HTTP-only cookies; never localStorage.
- Server-side RBAC and object authorization.
- Protect/mask bank account and personal contact fields.
- Encrypt provider refresh tokens/secrets at rest/application layer.
- Validate upload type/size.
- Verify webhook signatures/tokens.
- Rate-limit authentication/public endpoints.
- Never log credentials, bank account numbers, OAuth tokens, or full sensitive payloads.
- Use environment variables/secret manager.

## Engineering Quality

For every feature:
- migration
- model constraints
- service-layer business logic
- serializers/API
- authorization
- UI loading/error/empty states
- audit behavior
- tests
- docs updates

Add automated tests for:
- 90% advance
- each TDS mode
- approval revisions
- partial approval
- multi-vendor approval -> separate vendor payment transactions
- partial payment
- overpayment blocking
- payment reversal
- vendor isolation
- webhook duplicate delivery
- email thread mapping
- Excel import date/formula cases

## How to Work

1. Inspect the repository first.
2. Read `PRD.md` and `PLAN.md` completely.
3. If the repository is empty, create the monorepo structure and foundation.
4. Implement phases in dependency order.
5. Do not fake completed features. If an external credential is unavailable, implement the provider interface, fake adapter, configuration UI/status, webhook endpoints, and tests, then document the exact environment values needed for production.
6. Run migrations, tests, lint, typecheck, and builds frequently.
7. Fix failures before proceeding.
8. Keep commits/changes logically grouped if version-control operations are available.
9. Update a `docs/implementation-status.md` checklist as features are completed.
10. Do not replace requirements with a simpler generic CRUD app.

## First Execution Target

On the first implementation pass, deliver a fully runnable vertical slice:

```text
Login
-> Create vendor/vehicle/driver
-> Create NPL trip
-> Calculate 90% advance + configured 1% TDS
-> Create approval batch
-> Approver comments + approves
-> Approved item appears in finance queue grouped by vendor
-> Finance records payment + UTR
-> Payment is allocated to trip
-> Vendor ledger and trip ledger update
-> Audit trail shows the full chain
```

Then continue through the remaining phases in `PLAN.md`.

## Definition of Success

A manager should be able to open any trip and answer immediately:

```text
Which NPL indent is this?
Which vendor/vehicle was deployed?
What was the agreed vendor cost?
What advance was requested?
What TDS was deducted and on what base?
Who approved it and what did they comment?
How much cash was paid?
What is the UTR?
What balance remains?
What was the final vendor cost?
What did we bill NPL?
What is the trip profit?
```

Build for correctness and auditability first, then convenience.
