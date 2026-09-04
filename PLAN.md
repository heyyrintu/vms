# Implementation Plan

## NPL Transport Deployment, Vendor Advance & Payment Management System

This plan converts `PRD.md` into an incremental implementation sequence. Complete each phase with migrations, tests, documentation, and a working UI before moving to dependent phases.

---

## 1. Delivery Principles

- Treat `PRD.md` as the product source of truth.
- Keep business rules on the backend; the frontend may preview calculations but must not be authoritative.
- Use database transactions for approval/payment state changes.
- Use Decimal for all money calculations.
- Keep approval, payment, trip, and settlement states separate.
- Preserve complete audit history for financial changes.
- Build vendor-level payment transactions with trip-level allocations.
- Build integrations asynchronously and idempotently.
- Prefer a modular monolith over premature microservices.
- Keep the application multi-client capable even though NPL is the initial client.

---

## 2. Repository Structure

Recommended monorepo:

```text
/
  README.md
  PRD.md
  PLAN.md
  .env.example
  docker-compose.yml
  /apps
    /api          # Django + DRF
    /web          # Next.js + TypeScript
  /infra
    /docker
    /scripts
  /docs
    architecture.md
    api.md
    integrations.md
    operations.md
  /fixtures
    legacy-import-sample.xlsx or csv fixture with synthetic data
```

Backend modules/apps:

```text
core
accounts
clients
vendors
fleet
indents
trips
approvals
payments
settlements
billing
comments
notifications
integrations
imports
reports
audit
```

---

## 3. Phase 0 - Foundation

### Backend

- Bootstrap Django project.
- Configure PostgreSQL.
- Configure environment-based settings.
- Add Django REST Framework.
- Add OpenAPI/schema generation.
- Add Celery and Redis.
- Add structured logging and request IDs.
- Add health/readiness endpoints.
- Configure object storage abstraction.
- Add pytest test setup.

### Frontend

- Bootstrap Next.js with TypeScript.
- Configure Tailwind CSS and component library.
- Add layout/sidebar/navigation shell.
- Configure typed API client.
- Add query/cache layer.
- Add global error/loading states.
- Add reusable money/date/status components.

### DevOps

- Docker Compose for web, api, postgres, redis, worker, and local object storage if used.
- `.env.example` with placeholders only.
- Makefile/task runner commands for start, test, lint, migrate, seed.
- CI pipeline: backend lint/test, frontend lint/typecheck/test/build.

### Exit criteria

- `docker compose up` starts local stack.
- Web can call authenticated health API.
- CI passes.

---

## 4. Phase 1 - Authentication, RBAC, Organization Settings

### Implement

- User model / organization membership.
- Roles: Operations, Approver, Finance, Management, Transporter, Admin.
- Server-side permission helpers/policies.
- Secure session/JWT cookie strategy; no browser localStorage token persistence.
- Login/logout/password reset.
- Organization settings:
  - default currency
  - timezone
  - default advance percent = 90
  - default TDS rate = 1.00
  - allowed TDS policies
  - payment/approval settings
- Audit base model/middleware.

### Tests

- Role permission matrix.
- Unauthorized object access.
- CSRF/auth behavior.
- Audit actor/request correlation.

### Exit criteria

Each role sees only permitted navigation and server APIs reject unauthorized actions independently of UI.

---

## 5. Phase 2 - Masters: Client, Vendor, Vehicle, Driver

### Client

- Client CRUD.
- Seed NPL as first client, not hard-coded.

### Vendor

- Vendor CRUD/search.
- active/hold/inactive status.
- vendor contacts.
- bank account model with masking.
- default TDS profile/policy.

### Vehicle

- vehicle CRUD.
- normalized registration number.
- vendor association.
- vehicle type.

### Driver

- driver CRUD.
- vendor association optional.
- secure phone visibility.

### UI

- Vendor list/detail.
- Vehicle list/detail.
- Driver list/detail.
- Client/settings pages.

### Tests

- duplicates/normalization.
- vendor hold behavior scaffolding.
- bank data permission checks.

---

## 6. Phase 3 - Indents and Trips

### Models

- Indent.
- Trip.
- TripCharge.
- Document/attachment.

### Legacy fields

Implement all uploaded spreadsheet fields:

```text
FROM
TO
DATE
UOM-LTRS
QTY
TOTAL LOAD
RATES FOR VEHICLES
UNLOADING
TRANSPORTER
VH NO
DRIVER NAME
DRIVER NO
VH TYPE
EDD
```

Add:
- client
- NPL indent no
- trip no
- branch/cost center
- status
- advance percent
- TDS preview fields

### Trip number

Implement configurable human-readable numbering, e.g.:

```text
NPL-2026-000123
```

### UI

- Indent list/create/edit/detail.
- Trip register with spreadsheet-like columns.
- Trip create/edit/detail.
- filters/search/bulk selection.

### Tests

- required field validation.
- trip numbering concurrency.
- snapshot behavior for vendor/driver/vehicle display details.

---

## 7. Phase 4 - Financial Calculation Engine

Create a dedicated backend service/module for payment calculations. Do not scatter formulas through serializers/views.

### Functions

- calculate freight advance.
- calculate advance-eligible charges.
- resolve vendor/organization TDS policy.
- calculate current TDS.
- calculate cumulative TDS.
- calculate gross requested.
- calculate net requested.
- calculate final vendor gross cost.
- calculate remaining cash payable.
- calculate trip profitability.

### Required properties

- Decimal arithmetic.
- deterministic.
- unit tested.
- calculation breakdown object returned to UI.
- policy snapshot stored with approval item.

### Tests

At minimum:
- 90% of freight.
- unloading included in gross request.
- each TDS policy mode.
- prior TDS deduction handling.
- rounding rules.
- partial payment.
- final settlement.
- negative/invalid guard cases.

---

## 8. Phase 5 - Payment Approval Batches

### Backend

Implement:
- PaymentApprovalBatch.
- PaymentApprovalItem.
- ApprovalAction.
- ApprovalRule/ApprovalStage.
- revision model/logic.

### Features

- select multiple eligible trips.
- generate draft approval.
- vendor-grouped subtotals.
- batch gross/TDS/net totals.
- submit and lock snapshot.
- line-level and batch-level approve/reject/send-back.
- partial approval.
- sequential approval stages.
- material-change detection and re-approval.

### UI

- Payment Approval Builder.
- Approval Inbox.
- Approval detail with table and totals.
- clear status banner.
- revision diff display.

### Tests

- cannot approve without permission.
- submit locks financial snapshot.
- approved data changing causes new revision.
- partial approval totals.
- sequential approvers.
- self-approval restriction.

---

## 9. Phase 6 - Comments, Attachments, Activity Timeline

### Backend

- polymorphic/contextual comment model.
- @mentions.
- replies.
- INTERNAL / TRANSPORTER_VISIBLE visibility.
- attachments.
- system activity event records.

### UI

On approval and trip detail pages:
- timeline panel.
- composer.
- mentions.
- attachment upload.
- visible system events.

### Rules

- Reject and send-back require comment.
- Internal comments never appear in vendor channels.
- Edited comments preserve edit audit.

### Tests

- visibility filtering.
- permission rules.
- attachment authorization.
- mention notification creation.

---

## 10. Phase 7 - Finance Queue, Payments, Allocations, TDS Ledger

This is a critical phase.

### Models

- FinancePaymentTransaction.
- PaymentAllocation.
- TDSEntry.
- Payment reversal record/action.

### Finance queue

Approved items must appear grouped by vendor, even if their source approval batch includes multiple vendors.

### Payment creation

Finance can:
- select multiple approved items for one vendor.
- enter actual payment date.
- choose payment/bank account.
- enter UTR/reference.
- upload proof.
- record partial payment.
- mark payment paid.

### Invariants

- payment contains only one vendor.
- allocations identify trip and approval item.
- allocation totals equal transaction totals.
- no allocation above remaining approved amount.
- paid transaction cannot be deleted.
- corrections use reversal/adjustment workflow.
- duplicate UTR warning.

### UI

- Finance Pending Payments.
- payment composer.
- payment detail.
- payment register.
- TDS register.

### Tests

- multi-trip one-vendor payment.
- one approval batch -> multiple vendor payments.
- partial payments.
- overpayment blocking.
- reversal.
- TDS allocation.
- concurrent finance actions.

---

## 11. Phase 8 - Vendor Ledger and Trip Ledger

### Vendor ledger

Display:
- trip-linked approved amount
- TDS
- cash paid
- final settlement
- unresolved balances
- UTR/payment reference

### Trip ledger

Display:
- agreed freight
- advance request
- TDS deducted
- payment transactions
- charge adjustments
- final vendor cost
- remaining cash payable
- NPL billing
- margin

### Backend

Build ledger read models/services rather than storing a fragile running balance directly where possible.

### Tests

- ledger consistency after partial payments.
- settlement adjustments.
- payment reversal.

---

## 12. Phase 9 - Final Settlement and NPL Billing

### Settlement

- mark delivered/completed.
- POD/LR/vendor invoice attachments.
- final charge entry.
- final TDS computation.
- remaining cash payable.
- final settlement approval creation.

### NPL billing

- client billing amount.
- invoice/reference data.
- billing status.
- profitability calculation.

### Rules

- configurable required documents before settlement.
- TDS not treated as cost reduction for margin.

### Tests

- final balance calculation.
- additional taxable/non-taxable charges.
- settlement approval.
- closed trip restrictions.

---

## 13. Phase 10 - Notifications and In-App Inbox

### Build notification service

Channels:
- IN_APP
- EMAIL
- WHATSAPP

Use asynchronous jobs and outbox/idempotency pattern.

### Events

- approval requested
- @mention
- changes requested
- approved/rejected
- finance ready
- payment completed
- payment failed
- settlement pending

### Admin

- template editor/configuration.
- recipient rules.
- disable channel per event.

---

## 14. Phase 11 - Gmail Integration

### OAuth

- Google OAuth connection flow for authorized organizational mailbox.
- encrypted token storage.
- reconnect/revoke status.

### Outbound

- send approval and payment emails via Gmail API.
- stable approval/trip reference in subject.
- store Gmail message/thread IDs.

### Inbound

- configure Gmail `users.watch` with Google Cloud Pub/Sub.
- process mailbox history events.
- map incoming replies to approval/trip thread.
- store inbound message as integration activity/comment where policy permits.
- create manual reconciliation queue for unmapped replies.
- renewal job for mailbox watches.

### Reliability

- idempotency by provider event/message ID.
- retry transient failures.
- integration health/status page.

### Tests

- mocked OAuth/send.
- duplicate Pub/Sub delivery.
- thread mapping.
- disconnected mailbox behavior.

---

## 15. Phase 12 - WhatsApp Business Cloud API

### Configuration

- business account identifiers/tokens from environment/secure storage.
- webhook verification.
- approved template configuration.

### Outbound

- approval processing notification per vendor.
- payment completion notification per vendor.
- ensure vendor only sees own lines.

### Inbound

- webhook messages.
- delivered/read/failed statuses.
- map reply by provider context/message/vendor phone.
- attachment/media handling with secure storage.

### Reliability

- verify webhook requests.
- idempotent event processing.
- retry outbound transient errors.
- clear failed-message admin queue.

### Tests

- webhook verification.
- duplicate event.
- vendor isolation.
- status transitions.

---

## 16. Phase 13 - Dashboards and Reports

### Dashboard cards

- trips today
- vehicles deployed
- awaiting vehicle
- approval pending
- approved not paid
- paid today
- unsettled advance cash
- remaining vendor payable
- TDS month-to-date
- trips pending settlement
- POD pending
- billing pending
- gross margin

### Reports

Implement all PRD reports with:
- pagination
- filters
- totals
- CSV/XLSX export

Use database indexes and precomputed aggregates only when actual query performance requires them.

---

## 17. Phase 14 - Excel Import and Transition Tools

### Importer

- XLSX upload.
- exact legacy 17-column template support.
- column mapping UI.
- preview.
- row validation.
- create missing vendor/vehicle option.
- duplicate warning.
- atomic/import-batch behavior with per-row error reporting.
- import audit trail.

### Export

Provide an Excel export closely resembling the historical approval sheet so teams can transition gradually.

### Tests

- date serial conversion.
- Excel formulas vs values.
- malformed numeric/phone values.
- duplicate rows.
- partial import failure behavior.

---

## 18. Phase 15 - Hardening and Production Readiness

### Security

- object-level authorization review.
- secret scanning.
- webhook verification.
- file validation.
- auth/session review.
- rate limiting.
- sensitive field logging review.

### Data integrity

- constraints/indexes.
- financial transaction atomicity.
- race-condition tests.
- backup/restore test.

### Performance

- query count checks.
- indexes for common trip/vendor/payment searches.
- pagination on large tables.

### Operations

- deployment docs.
- migrations runbook.
- integration setup docs.
- backup/restore runbook.
- admin user bootstrap.
- health checks.

---

## 19. Test Strategy

### Unit tests

Focus on:
- advance calculations
- TDS policies
- settlement calculations
- permissions
- state transitions

### API tests

- CRUD permissions
- approval actions
- finance payment/allocation
- import endpoints
- integration webhooks

### Integration tests

- database transactions
- async job enqueueing
- storage attachment flows
- Gmail/WhatsApp adapters using mocked provider APIs

### End-to-end tests

Automate at least these flows:

1. Create trip -> approval -> approve -> finance pays -> ledger updates.
2. Multiple vendors in one approval -> separate vendor payments.
3. Approver sends back -> operations changes rate -> resubmits -> revised approval.
4. Partial finance payment -> second payment -> settled.
5. Trip completed -> final charges -> final settlement approval -> paid.
6. Cancelled trip after advance -> recovery workflow.
7. Gmail reply becomes approval timeline message.
8. WhatsApp payment notification records delivery status.

---

## 20. Seed/Demo Data

Create synthetic demo data modeled on the current workflow, but do not copy real driver phone numbers or sensitive bank data from production files.

Seed:
- NPL client
- 4-5 synthetic vendors
- multiple vehicles/drivers
- trips on Sonipat -> Ghaziabad / Delhi / Moradabad style routes
- rates, unloading, 90% advance examples
- 1% TDS policy
- approval batches in multiple states
- paid and unsettled examples

---

## 21. Definition of Done for Every Feature

A feature is done only when:

- database migration exists if needed
- backend validation/authorization exists
- API endpoint is documented
- frontend handles loading/error/empty states
- audit behavior is implemented where required
- tests cover critical paths
- no secrets are committed
- lint/typecheck/tests pass
- relevant docs are updated

---

## 22. First Production Slice

The first usable production slice should contain:

1. Auth/RBAC.
2. Client/vendor/vehicle/driver masters.
3. Indent + trip register.
4. 90% advance + configurable 1% TDS engine.
5. Payment approval batches.
6. Comments/attachments/approval actions.
7. Finance vendor-grouped queue.
8. Payment + UTR + trip allocations.
9. Vendor/trip ledger.
10. Core dashboard/reports.
11. Gmail outbound approval notifications.
12. Audit log.

Then add inbound Gmail, WhatsApp, historical Excel import, and full settlement enhancements without changing the core payment data model.

