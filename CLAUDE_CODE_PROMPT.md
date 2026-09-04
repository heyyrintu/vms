# Claude Code Build Prompt

Act as the lead full-stack engineer responsible for implementing the repository described by `PRD.md` and `PLAN.md`.

## Context

We operate transport deployments for a client (initially NPL) using multiple transporters/vendors. For each vehicle deployment we usually request a 90% freight advance, include unloading/other advance-eligible charges, deduct TDS (requested default 1%), send the payment sheet for management approval, notify the transporter, and send approved items to finance for payment. Finance records the payment/UTR. Later the trip is completed and the final vendor cost/balance is settled.

The existing process is an Excel approval sheet plus Gmail and WhatsApp. The application must become the system of record while preserving spreadsheet-like usability.

The uploaded legacy Excel structure maps to these columns:

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

Legacy calculations:

```text
ADVANCE = vehicle rate * 90%
TOTAL PAYMENTS TO BE DONE = ADVANCE + UNLOADING
```

The new system adds TDS, approval workflow, comments, finance processing, vendor/trip ledgers, final settlement, dashboards, Gmail, WhatsApp, and audit history.

## Before Editing Anything

1. Read `PRD.md` fully.
2. Read `PLAN.md` fully.
3. Inspect the current repository, migrations, tests, package files, and environment examples.
4. Build a concrete implementation checklist based on what already exists.
5. Preserve working code and evolve it; do not blindly regenerate an existing app.

If the repository is empty, bootstrap the architecture defined below.

## Target Stack

Monorepo:

```text
apps/api  -> Django + Django REST Framework
apps/web  -> Next.js + React + TypeScript
infra     -> Docker/scripts
```

Infrastructure:
- PostgreSQL
- Redis
- Celery
- S3-compatible document storage
- Docker Compose

Frontend:
- Next.js
- TypeScript strict mode
- Tailwind
- accessible reusable UI components
- typed API client
- query/cache library for server state

Use current stable compatible versions and commit lockfiles.

## Architectural Rules

- Modular monolith, not microservices.
- Backend owns all business rules and financial calculations.
- Use Decimal for money.
- Use database transactions for financial/approval state changes.
- Use constraints and idempotency keys for data integrity.
- Keep integration adapters behind interfaces so tests/local development do not require real Gmail/WhatsApp credentials.
- External notifications must use queued jobs; never block an approval/payment transaction on a provider call.
- Append audit events for important state/financial changes.

## Domain Invariants You Must Protect

### Trip traceability

Every approval item and payment allocation must link to a trip.

### Multi-vendor approvals

An approval batch may contain several vendors.

### Vendor-specific payments

A real finance payment transaction belongs to exactly one vendor. If an approval contains three vendors, finance creates separate payment transactions for those vendors as needed.

### Allocations

A payment may cover multiple approved trips for the same vendor. PaymentAllocation records must reconcile the payment to the individual trips.

### Locked approvals

Submitted/approved monetary snapshots cannot be silently edited. Material changes generate a revision and re-approval requirement.

### Payment immutability

A paid transaction is never hard-deleted. Use reversal/adjustment workflows.

### Transporter privacy

A transporter can see/receive only its own data. Never send full multi-vendor approval content to one transporter.

### Comments privacy

INTERNAL comments never leave the internal application. Only explicitly TRANSPORTER_VISIBLE content may appear externally.

## Calculation Engine

Create one tested backend service for calculations.

Default advance:

```text
freight_advance_gross = vendor_freight_rate * 0.90
```

Use configurable advance percent instead of a hard-coded 0.90 in business records.

Gross request:

```text
gross_requested = freight_advance_gross
                + advance_eligible_charges
                - advance_stage_deductions
```

TDS:
- seed/default requested rate: 1.00%
- rate configurable by organization/vendor
- taxable basis/policy configurable
- do not claim or encode a universal statutory rule

Support these modes:

```text
PER_PAYMENT_TAXABLE_AMOUNT
FULL_FREIGHT_AT_FIRST_ADVANCE
CUMULATIVE_TRIP_LIABILITY
MANUAL_WITH_APPROVAL
```

Net request:

```text
net_requested = gross_requested - tds_this_payment
```

Final settlement:

```text
final_vendor_gross_cost = final freight + additions - deductions
net_vendor_payable_total = final_vendor_gross_cost - total_tds_required
remaining_cash_payable = net_vendor_payable_total - total_cash_paid
```

Trip profit:

```text
client billing - vendor gross cost - internal trip costs
```

Do not subtract TDS from economic vendor cost when calculating margin.

## Build the Domain Model

Implement the models specified in the PRD, including:

- OrganizationSettings
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
- ApprovalRule / ApprovalStage
- ApprovalAction
- Comment / Activity
- Document
- FinancePaymentTransaction
- PaymentAllocation
- TDSEntry
- FinalTripSettlement
- ClientBilling
- IntegrationConnection
- IntegrationMessage
- AuditLog

Use clear enums for trip, approval, finance payment, and settlement state. Do not overload one status field for the entire lifecycle.

## UX Expectations

The application is an operations tool. Favor speed, dense readable tables, and clear financial breakdowns over decorative dashboards.

Required screens:
- Dashboard
- Trip Register
- Trip Detail
- Vendor List/Detail
- Payment Approval Builder
- Approval Inbox
- Approval Detail with Activity/Comments
- Finance Pending Payments grouped by vendor
- Payment Create/Detail
- Vendor Ledger
- Trip Ledger
- Payment Register
- TDS Register
- Reports
- Settings
- Excel Import

Trip register should feel familiar to users coming from Excel.

## Approval Discussion

Build contextual discussion rather than a generic forum.

Features:
- comments
- replies
- @mentions
- attachments
- internal/transporter visibility
- system activity events
- immutable approval actions

Reject/send-back requires a reason.

## Gmail

Create a Gmail provider interface and fake adapter first, then production implementation.

Production requirements:
- Google OAuth
- Gmail API outbound send
- store message/thread IDs
- subject references such as `[PA-2026-000128]`
- Gmail mailbox watch using `users.watch` + Google Cloud Pub/Sub
- process history/messages to capture replies
- idempotent inbound processing
- renew expiring watches
- unmapped-message reconciliation queue

Never require production credentials for the test suite.

## WhatsApp

Create a WhatsApp provider interface and fake adapter first, then production Cloud API implementation.

Requirements:
- official WhatsApp Business Cloud API
- outbound templates where required
- webhook verification
- inbound reply capture
- sent/delivered/read/failed status
- idempotent events
- provider message IDs saved
- strict vendor-data isolation

## Finance Flow

After approval:

```text
Approved approval items
-> Finance queue grouped by vendor
-> Finance selects one vendor's items
-> Create payment transaction
-> Enter payment date/bank/mode/UTR/proof
-> Allocate gross/TDS/net amounts to selected trips
-> Mark paid
-> Update trip/vendor ledger
-> Queue transporter notification
```

Support partial payments.

Prevent:
- mixing vendors in one payment
- paying unapproved items
- over-allocation
- negative accidental balances
- editing a paid transaction without reversal

## Legacy Excel Import

Implement import with:
- XLSX upload
- exact 17-column legacy mapping
- preview
- Excel serial date conversion
- validation
- normalization of vehicle registration
- vendor lookup/create-with-review
- duplicate warnings
- import batch audit

Test with synthetic fixtures only.

## Security

- RBAC enforced in backend.
- Object-level vendor isolation.
- Secure HTTP-only auth cookies; no auth tokens in localStorage.
- Sensitive bank/contact data masked by role.
- OAuth/provider tokens encrypted and never logged.
- Validate uploads.
- Validate webhook signatures/tokens.
- Rate-limit auth/public endpoints.
- Keep secrets in environment/secret manager.

## Testing Standard

Do not consider a financial feature complete without tests.

Cover:
- calculation service
- all TDS policies
- permissions
- approval revisions
- partial approval
- multi-vendor batch -> multiple vendor payments
- partial payments
- overpayment prevention
- reversal
- cancelled trip after advance
- vendor isolation
- integration webhook idempotency
- Gmail thread mapping
- import date/formula handling

Add end-to-end coverage for the primary workflow.

## Implementation Order

Follow `PLAN.md`. Prioritize a vertical slice before integrations:

```text
Auth/RBAC
-> Masters
-> Trip
-> Calculation engine
-> Approval
-> Comments
-> Finance payment + allocations
-> Vendor/trip ledger
-> Final settlement
-> Notifications
-> Gmail
-> WhatsApp
-> Reports/import/hardening
```

## Working Style

- Keep a short implementation checklist in `docs/implementation-status.md`.
- Make small coherent changes.
- Run tests/typecheck/lint/build after meaningful batches of changes.
- Fix failures before claiming completion.
- If credentials are unavailable, implement fake adapters, integration contracts, config screens, webhook routes, and mocked tests instead of skipping the feature.
- Avoid TODO-only stubs in core business flows.
- Document any intentional deviation from `PRD.md` in `docs/architecture.md` with rationale.

## First Vertical Slice Acceptance Test

The first complete workflow must allow:

1. Admin creates NPL + roles/settings.
2. Operations creates vendor, vehicle, driver, and trip.
3. App calculates 90% advance and configured 1% TDS with visible breakdown.
4. Operations creates/submits approval batch.
5. Approver comments and approves.
6. Approved item appears in finance queue under the correct vendor.
7. Finance records payment and UTR.
8. Payment allocates to the trip.
9. Trip ledger and vendor ledger show gross, TDS, cash paid, and remaining balance.
10. Audit timeline shows creation, submission, approval, and payment.

When this works with tests and a usable UI, continue with the rest of `PLAN.md`.

## Definition of Success

For any trip, a permitted user must be able to determine without checking Excel, Gmail, or WhatsApp:

- NPL indent
- route/date/vehicle/driver
- transporter
- agreed freight cost
- 90% advance basis
- unloading/other charges
- TDS base/rate/amount
- approval history/comments
- payment date/UTR
- cash paid
- remaining vendor payable
- final vendor cost
- NPL billing
- trip profit

Build the product so the web app is the source of truth and Gmail/WhatsApp are synchronized communication channels around it.
