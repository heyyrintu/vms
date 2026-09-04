# Product Requirements Document (PRD)

## NPL Transport Deployment, Vendor Advance & Payment Management System

**Document status:** Build-ready v1  
**Primary client/workflow:** NPL transport deployments  
**Product type:** Internal operations + approval + finance web application with transporter notifications  
**Default currency:** INR  
**Default business timezone:** Configurable; seed configuration may use Asia/Kolkata  

---

## 1. Product Summary

The product is a web application for managing transport indents, vehicle deployments, transporter/vendor costs, advance payment approvals, TDS deductions, finance processing, trip settlement, and trip-wise/vendor-wise financial tracking.

The current operational process is spreadsheet-driven. Operations prepares a vehicle deployment/payment approval sheet, calculates a 90% advance on the vehicle rate, adds unloading/other eligible charges, emails the sheet for approval, and then follows up with the transporter and finance team. Payment status, UTR/reference details, final trip cost, vendor balances, and approval discussions are difficult to track across Excel, email, WhatsApp, and separate finance records.

The application will convert this into a controlled workflow:

```text
NPL Indent
  -> Trip / Vehicle Deployment
  -> Vendor Rate & Advance Calculation
  -> Payment Approval Batch
  -> Approval Discussion / Approval
  -> Transporter Notification
  -> Finance Payment Queue
  -> Payment + UTR
  -> Trip Completion
  -> Final Vendor Settlement
  -> NPL Billing / Revenue
  -> Trip Profitability / Closure
```

Every financial event must remain traceable to the relevant trip, vendor, vehicle, approval, payment, and user action.

---

## 2. Problem Statement

The current process has several operational risks:

1. Payment approvals are prepared manually in spreadsheets and sent over email.
2. Advance calculations are not centrally controlled.
3. Approval comments are scattered across email/WhatsApp conversations.
4. Finance may receive an approved total without a structured, trip-wise allocation.
5. A single approval batch can contain multiple transporters, while actual bank payments are vendor-specific.
6. TDS deduction needs to be calculated and tracked consistently.
7. Payment UTRs and dates are difficult to reconcile against individual trips.
8. Vendor advance outstanding and trip settlement balances are not visible in real time.
9. Rate changes after approval may not be obvious.
10. Transporters need timely approval/payment communication without seeing other vendors' information.
11. Historical trip, payment, and vendor performance information is difficult to search.
12. NPL billing and trip profitability are not automatically connected to vendor costs.

---

## 3. Product Goals

### 3.1 Primary goals

- Create one system of record for NPL indents, trips, transporters, vehicles, approvals, and payments.
- Preserve the familiar spreadsheet-style operational workflow while adding database integrity and audit controls.
- Automatically calculate the configured advance percentage, defaulting to 90%.
- Automatically calculate TDS using a configurable policy, with a default requested rate of 1.00%.
- Allow multiple trips to be submitted in one payment approval batch.
- Support approval, rejection, send-back, comments, attachments, and @mentions.
- Automatically send approved requests to the finance queue.
- Notify only the relevant transporter about their own trip/payment information.
- Record finance payment date, amount, bank/reference/UTR, proof, and allocations.
- Maintain vendor-wise and trip-wise ledgers.
- Track final trip settlement and outstanding amounts.
- Integrate Gmail for outgoing approval/payment emails and inbound reply capture.
- Integrate WhatsApp Business for transporter notifications and inbound replies/status updates.
- Provide dashboards and exportable reports.
- Maintain a tamper-evident audit trail of important business changes.

### 3.2 Secondary goals

- Import historical/current Excel sheets into structured records.
- Support clients other than NPL in the future without redesigning the schema.
- Support multiple branches, cost centers, and approval rules.
- Provide a secure vendor-facing view/portal in a later phase.
- Support future bank/payment API integration without changing the core ledger model.

---

## 4. Non-Goals for MVP

The MVP will not:

- Execute bank transfers directly.
- Replace a full accounting/ERP/general-ledger product.
- File TDS returns or provide tax/legal advice.
- Perform GPS vehicle tracking.
- Provide route optimization.
- Provide a marketplace for vehicle sourcing.
- Automatically approve payments using AI.
- Expose internal approval comments to transporters unless a comment is explicitly marked transporter-visible.

---

## 5. Current Excel Workflow Mapping

The uploaded legacy payment approval workbook contains these columns:

| Legacy Excel Column | New System Field | Notes |
|---|---|---|
| SR NO | import_row_no | Import/reference only |
| FROM | trip.origin | Required |
| TO | trip.destination | Required |
| DATE | trip.deployment_date | Required |
| UOM-LTRS | trip.uom_ltrs | Preserve as provided |
| QTY | trip.quantity | Decimal/number |
| TOTAL LOAD | trip.total_load | Decimal/number |
| RATES FOR VEHICLES | trip.vendor_freight_rate | Money |
| UNLOADING | trip_charge.unloading_advance | Money |
| ADVANCE | payment_request.freight_advance_gross | Legacy formula: vehicle rate x 90% |
| TOTAL PAYMENTS TO BE DONE | payment_request.gross_requested | Legacy formula: advance + unloading |
| TRANSPORTER | vendor.name | Vendor master lookup |
| VH NO | vehicle.registration_no | Normalized uppercase registration |
| DRIVER NAME | driver.name | Trip-specific snapshot retained |
| DRIVER NO | driver.phone | Stored securely and role-limited |
| VH TYPE | trip.vehicle_type | Configurable master/value |
| EDD | trip.expected_delivery_date | Date |

### New fields added by the system

- Client
- NPL indent number
- Internal trip ID
- Branch/cost center
- Purchase/reference document number, if applicable
- Advance percentage
- TDS rate
- TDS calculation basis/mode
- TDS amount on this payment
- Gross approval amount
- Net payment amount
- Approval batch number
- Approval status
- Approver(s)
- Approval comments
- Finance status
- Payment transaction ID
- Payment date
- UTR/reference number
- Paid amount
- Payment proof
- Trip completion status
- POD/LR/vendor invoice attachments
- Final vendor cost
- Total TDS deducted
- Total cash paid
- Remaining net payable
- NPL billing amount
- Gross margin and margin percentage

---

## 6. User Roles and Permissions

### 6.1 Operations

Can:
- Create/edit draft indents and trips.
- Select vendor, vehicle, driver, rate, unloading, and other charges.
- Create payment approval batches.
- Submit for approval.
- Comment and attach documents.
- View payment status and trip ledger.

Cannot:
- Approve own requests unless an explicit organization policy permits it.
- Mark payments as paid.
- Modify finance transaction details.
- Change approved financial fields without triggering re-approval.

### 6.2 Approver / Manager

Can:
- View approval batches and underlying trips.
- Approve whole batch or selected lines.
- Reject lines/batch.
- Send back for correction.
- Comment, @mention users, and add attachments.
- View previous revisions and audit history.

### 6.3 Finance

Can:
- View approved items grouped by vendor.
- Create payment transactions.
- Allocate one payment to one or more approved trip items for the same vendor.
- Record bank account, payment date, UTR/reference, paid amount, TDS, proof, and remarks.
- Mark payments paid/failed/reversed with controlled workflow.
- View vendor ledger and TDS ledger.

Cannot:
- Silently modify approved vendor rate/charges.

### 6.4 Management

Can:
- View all operational and financial dashboards.
- View vendor exposure, pending approvals, payment pipeline, outstanding advances, unsettled trips, TDS, and profitability.
- Export reports.
- Receive escalations.

### 6.5 Transporter / Vendor

MVP behavior:
- Receives approved/payment notifications by configured email and/or WhatsApp.
- Receives only their own trip/payment information.
- May open a secure, time-limited vendor-facing payment/trip page if enabled.

Later full portal:
- Login and view own trips, payments, TDS, balances, POD/invoice upload, and messages.

### 6.6 Administrator

Can:
- Manage users, roles, clients, branches, masters, integrations, approval matrix, TDS policy, notification templates, and system settings.

---

## 7. Core Business Objects

### 7.1 Client

Fields:
- id
- code
- name
- active
- billing settings
- default branch/cost center where relevant

NPL will be seeded as the initial client, but client must not be hard-coded.

### 7.2 Vendor / Transporter

Fields:
- id
- vendor_code
- legal_name
- display_name
- status: ACTIVE / HOLD / INACTIVE
- primary_contact_name
- primary_phone
- email
- address
- PAN/GST or organization-defined identifiers where required
- default_tds_rate
- default_tds_policy
- payment_terms
- bank accounts
- notes
- blocked_reason
- created_at / updated_at

Vendor bank details must be permission-protected and masked in normal views.

### 7.3 Vehicle

Fields:
- id
- registration_no
- vendor_id
- vehicle_type
- capacity
- active
- notes

Registration number should be normalized for search/deduplication.

### 7.4 Driver

Fields:
- id
- name
- phone
- vendor_id optional
- active

Each trip must also store a snapshot of driver name/phone so historical trips do not change when master data changes.

### 7.5 Indent

Fields:
- id
- indent_no
- client_id
- indent_date
- branch/cost_center
- origin
- destination
- reporting_datetime
- expected_delivery_date
- uom_ltrs
- quantity
- total_load
- required_vehicle_type
- customer_reference
- notes
- status
- attachments

### 7.6 Trip / Deployment

Fields:
- id
- trip_no, human readable, e.g. NPL-2026-000123
- indent_id
- client_id
- origin/destination snapshot
- deployment_date/time
- expected_delivery_date
- actual_delivery_date/time
- vendor_id
- vehicle_id / vehicle number snapshot
- driver_id / driver snapshot
- vehicle_type
- vendor_freight_rate
- status
- POD status
- settlement status
- client_billing_amount
- notes

### 7.7 Trip Charge

Line-item model so charges remain explainable.

Fields:
- id
- trip_id
- charge_type: FREIGHT / UNLOADING / DETENTION / LOADING / TOLL / OTHER / DEDUCTION / REIMBURSEMENT
- description
- amount
- direction: ADD / DEDUCT
- advance_eligible boolean
- tds_eligible boolean
- supporting_document optional
- source: INITIAL / FINAL_SETTLEMENT / MANUAL_ADJUSTMENT
- created_by

### 7.8 Payment Approval Batch

Represents the approval request that replaces the current Excel/email approval sheet.

Fields:
- id
- approval_no, e.g. PA-2026-000128
- client_id
- requested_by
- submitted_at
- status: DRAFT / PENDING / CHANGES_REQUESTED / PARTIALLY_APPROVED / APPROVED / REJECTED / CANCELLED
- revision_no
- approval_rule_snapshot
- totals: gross requested, TDS, net requested
- current_approver(s)
- purpose: ADVANCE / FINAL_SETTLEMENT / OTHER

A batch may contain multiple vendors and trips.

### 7.9 Payment Approval Item

One approval line tied to exactly one trip and one vendor.

Fields:
- id
- approval_batch_id
- trip_id
- vendor_id
- freight_rate_snapshot
- advance_percent
- freight_advance_gross
- unloading_advance
- other_advance_eligible_charges
- gross_requested
- tds_rate
- tds_policy_snapshot
- tds_base
- tds_this_request
- net_requested
- item_status
- approver_note

### 7.10 Comment / Discussion Thread

Every approval batch and trip has an activity thread.

Fields:
- id
- object_type
- object_id
- author
- body
- visibility: INTERNAL / TRANSPORTER_VISIBLE
- parent_comment optional
- attachments
- mentions
- created_at
- edited_at

Reject and send-back actions require a reason/comment.

### 7.11 Approval Action

Immutable record:
- actor
- action: SUBMIT / APPROVE / REJECT / SEND_BACK / CANCEL / REOPEN
- scope: BATCH / ITEM
- object_id
- comment
- timestamp
- approval stage
- captured amount/totals at action time

### 7.12 Finance Payment Transaction

A real-world payment record. A payment transaction belongs to one vendor and may allocate to multiple approved trip items for that vendor.

Fields:
- id
- payment_no
- vendor_id
- payment_date
- bank_account_id / masked bank name
- payment_mode
- utr_reference
- gross_allocated_amount
- tds_amount
- net_paid_amount
- status: DRAFT / PROCESSING / PAID / FAILED / REVERSED
- proof_document
- remarks
- created_by
- paid_by
- paid_at

Important: One approval batch with five vendors can result in five or more finance payment transactions.

### 7.13 Payment Allocation

Fields:
- payment_id
- approval_item_id
- trip_id
- gross_amount_allocated
- tds_allocated
- net_cash_allocated

This is the key table that preserves trip-wise traceability.

### 7.14 TDS Entry

Fields:
- vendor_id
- trip_id
- payment_id
- taxable_base
- rate
- tds_amount
- policy_snapshot
- deduction_date
- status
- finance_reference optional

### 7.15 Final Trip Settlement

Fields:
- trip_id
- final_freight
- charge lines
- deductions
- total_vendor_gross_cost
- total_tds_required
- total_tds_deducted
- total_net_vendor_payable
- total_cash_paid
- remaining_cash_payable
- settlement_approval_id optional
- settlement_status

### 7.16 Client Billing

Fields:
- trip_id
- client_id
- billing_amount
- invoice_no
- invoice_date
- payment_status
- received_amount optional
- notes

### 7.17 Integration Message

Unified record for EMAIL / WHATSAPP / IN_APP.

Fields:
- channel
- direction: OUTBOUND / INBOUND
- external_message_id
- external_thread_id
- object_type/object_id
- vendor/user/contact
- template_id optional
- subject optional
- body summary
- status: QUEUED / SENT / DELIVERED / READ / FAILED / RECEIVED
- raw_metadata JSON with sensitive data minimized
- sent_at / received_at
- retry_count

### 7.18 Audit Log

Append-only/tamper-evident log containing:
- actor
- action
- object type/id
- before/after diff for tracked fields
- timestamp
- request/correlation ID
- source: UI / API / IMPORT / INTEGRATION / SYSTEM

---

## 8. Financial Calculation Rules

All money fields must use decimal/fixed precision. Never use floating-point arithmetic for money.

### 8.1 Advance

Default requested advance percentage:

```text
advance_percent = 90.00%
freight_advance_gross = vendor_freight_rate * advance_percent
```

The percentage is configurable by organization, vendor, trip, or authorized override.

### 8.2 Gross approval request

```text
gross_requested = freight_advance_gross
                + unloading_advance
                + other advance-eligible charges
                - advance-stage deductions
```

### 8.3 TDS

The business has requested a default TDS rate of 1.00%. The software must not hard-code a legal interpretation of the taxable base. Finance/admin must be able to configure the TDS policy.

Supported policy modes:

1. `PER_PAYMENT_TAXABLE_AMOUNT`
   - TDS is calculated on the taxable amount included in the current payment request.

2. `FULL_FREIGHT_AT_FIRST_ADVANCE`
   - The configured TDS on the full freight base can be deducted in the first eligible payment.

3. `CUMULATIVE_TRIP_LIABILITY`
   - System calculates cumulative TDS required on the trip to date, subtracts TDS already deducted, and deducts only the difference.

4. `MANUAL_WITH_APPROVAL`
   - Authorized finance user enters TDS amount/basis; reason is mandatory and audited.

Generic calculation:

```text
tds_target = configured_taxable_base * tds_rate
previous_tds = sum(tds already deducted for the same trip/base)
tds_this_payment = max(0, tds_target - previous_tds)   # for cumulative modes
net_payment = gross_requested - tds_this_payment
```

The UI must show the exact base, rate, TDS amount, and net payable before submission.

A production rollout must have finance confirm the organization's TDS policy configuration.

### 8.4 Final settlement

```text
total_vendor_gross_cost = final freight
                        + additive trip charges
                        - vendor deductions

total_tds_required = TDS policy applied to final taxable base
net_vendor_payable_total = total_vendor_gross_cost - total_tds_required
remaining_cash_payable = net_vendor_payable_total - total_cash_paid_to_vendor
```

Non-TDS-eligible/pass-through charge types must still be payable if configured but excluded from the TDS base.

### 8.5 Profitability

```text
gross_profit = client_billing_amount - total_vendor_gross_cost - other_internal_trip_costs
margin_percent = gross_profit / client_billing_amount * 100
```

Avoid mixing TDS withholding with economic vendor cost when calculating profit.

---

## 9. Core Workflows

### 9.1 Create Indent and Trip

1. Operations creates or imports NPL indent.
2. Create one or more trips/deployments from the indent.
3. Assign transporter/vendor.
4. Assign vehicle/driver.
5. Enter rate and applicable charges.
6. System calculates advance/TDS/net amount.
7. Trip is eligible for payment approval submission.

### 9.2 Create Payment Approval Batch

1. User selects one or more eligible trips.
2. System creates draft approval batch.
3. Each trip is one approval item.
4. System shows batch totals and vendor-group subtotals.
5. User reviews supporting documents/comments.
6. User submits.
7. Financial fields included in the submission snapshot become locked.

### 9.3 Approval

Approver screen must show:
- batch details
- all trip lines
- vendor grouped subtotal
- gross, TDS, net totals
- supporting documents
- previous revision history
- comments/activity timeline

Actions:
- Approve all
- Approve selected lines
- Reject selected lines
- Send batch/items back for changes
- Comment / @mention

Rules:
- Reject/send-back requires comment.
- Approval is timestamped and immutable.
- Partial approval must produce clear per-line states and totals.
- Approved items automatically become available to finance.

### 9.4 Material Change / Re-Approval

After submission/approval, changes to protected fields must create a new revision and invalidate the previous approval where configured.

Protected fields include:
- vendor
- vehicle rate
- advance percent
- unloading/other payable charges
- TDS base/rate/policy
- vendor
- net payable
- trip identity

The UI must show:

```text
Old value -> New value
Changed by
Changed at
Reason
Re-approval required
```

### 9.5 Finance Payment

1. Approved items appear in Finance -> Pending Payments.
2. Queue is grouped by vendor.
3. Finance selects one or more items for the same vendor.
4. System creates payment transaction.
5. Finance verifies gross/TDS/net amounts.
6. Finance enters payment date, bank, UTR/reference, actual amount, and proof.
7. System prevents overpayment beyond approved/remaining amount except explicit override permission with reason.
8. Payment is marked PAID.
9. Allocations update all linked trip/vendor ledgers.
10. Transporter receives payment confirmation if notifications are enabled.

### 9.6 Transporter Notification

After approval:
- Send transporter an approval/payment-processing notification containing only that vendor's own trips.

After payment:
- Send payment confirmation with trip(s), gross allocation, TDS, net paid, payment date, and UTR/reference where allowed.

Do not include:
- other vendors
- internal comments
- management-only notes
- unrelated batch totals

### 9.7 Trip Completion and Final Settlement

1. Operations marks trip delivered/completed.
2. POD/LR/vendor invoice and supporting documents are uploaded.
3. Final freight/charges/deductions are entered.
4. System recalculates final vendor liability, TDS, cash paid, and remaining payable.
5. If remaining payable > 0, create final settlement approval.
6. Final payment follows the same approval -> finance workflow.
7. Trip becomes SETTLED only when settlement requirements are satisfied.

### 9.8 Cancellation After Advance

If a trip is cancelled after payment:
- Never delete payment history.
- Mark trip CANCELLED_WITH_PAYMENT.
- Create recovery/adjustment balance.
- Require resolution method: REFUND / ADJUST_AGAINST_FUTURE_TRIP / WRITE_OFF_WITH_APPROVAL / OTHER.
- Maintain full audit trail.

---

## 10. Approval Matrix

Approval rules must be configurable, not coded into business logic.

Rules can use:
- client
- branch
- payment purpose
- gross batch amount
- net batch amount
- individual trip amount
- vendor risk/hold status
- user/department

Example configuration:

```text
0 - 25,000          -> Operations Manager
25,001 - 100,000    -> Operations Manager + Finance Manager
Above 100,000       -> Operations Manager + Finance Manager + Director
```

The app must support sequential approval stages and preserve a snapshot of the rule used at submission time.

---

## 11. Comments, Mentions, and Activity Timeline

Do not build a standalone social forum for MVP.

Build contextual discussion threads on:
- Payment Approval Batch
- Trip
- Finance Payment

Features:
- plain text comments
- @mentions
- attachments
- reply-to-comment
- internal vs transporter-visible visibility
- edit window policy; edit history retained
- system-generated activity entries

System timeline events include:
- record created
- rate changed
- approval submitted
- comment added
- approval/rejection/send-back
- transporter notification sent
- finance payment started
- UTR recorded
- payment marked paid
- email/WhatsApp delivered/read when available
- POD uploaded
- trip settled

---

## 12. Gmail Integration

### 12.1 Objectives

- Send approval request emails.
- Send approval outcome emails.
- Send finance notifications.
- Send transporter payment emails where configured.
- Capture replies into the correct approval/trip discussion timeline.

### 12.2 Design

Use Google OAuth and Gmail API for connected mailbox functionality.

Store:
- Google account connection metadata
- access/refresh credentials securely/encrypted
- Gmail message ID
- Gmail thread ID
- approval/trip correlation

Outbound email subjects must include stable system reference IDs such as:

```text
[PA-2026-000128] NPL Vehicle Advance Approval - INR 452,300
```

Inbound mapping preference:
1. known Gmail thread ID
2. custom correlation metadata where possible
3. approval ID found in subject
4. manual reconciliation queue if ambiguous

For near-real-time inbound processing, implement Gmail mailbox watch notifications via Google Cloud Pub/Sub and then fetch history/messages using the Gmail API. Renew mailbox watches before expiration.

Requirements:
- idempotent webhook/event processing
- no duplicate comments/messages
- store only required email metadata/body content
- preserve attachment links/files according to retention policy
- OAuth disconnect/reconnect handling

---

## 13. WhatsApp Business Integration

Use the official WhatsApp Business Platform / Cloud API.

### 13.1 Outbound events

Possible templates:
- payment approval accepted / processing
- payment completed
- trip document request
- settlement discrepancy request

Example payment confirmation content:

```text
Payment processed
Trip: NPL-2026-000123
Vehicle: HRXXAB1234
Route: Sonipat -> Ghaziabad
Gross allocation: INR 45,000
TDS: INR 500
Net paid: INR 44,500
UTR: XXXXXXXX
```

### 13.2 Inbound events

Capture:
- transporter text reply
- delivery status
- read status where available
- media/documents where permitted

Mapping order:
1. replied-to message ID
2. active vendor conversation + phone
3. trip/approval reference in message
4. manual reconciliation queue

### 13.3 Safety/privacy rules

- Use approved message templates where required by WhatsApp rules.
- Do not send information about other vendors.
- Keep internal comments internal.
- Make notification preferences configurable.
- Store provider IDs/statuses for troubleshooting.
- Webhook handling must be verified and idempotent.

---

## 14. Required Screens

### 14.1 Dashboard

KPIs with date/client/branch/vendor filters:
- Trips today
- Vehicles deployed
- Trips awaiting vehicle
- Approval pending amount
- Approved / finance pending
- Payments processed today
- Vendor advance outstanding
- TDS deducted this month
- Trips pending settlement
- POD pending
- Client billing pending
- Gross margin

### 14.2 Indent List

- spreadsheet-like table
- filters/search
- status
- create/import
- bulk create trip/payment approval where applicable

### 14.3 Trip Register

Primary operational screen.

Columns:
- trip no
- indent no
- client
- date
- origin
- destination
- transporter
- vehicle no
- vehicle type
- vendor rate
- advance
- unloading
- TDS
- net paid
- balance
- trip status
- payment status
- EDD

### 14.4 Trip Detail

Tabs/sections:
- Overview
- Cost & Charges
- Payments
- Documents
- NPL Billing
- Activity
- Audit History

### 14.5 Payment Approval Builder

- select eligible trips
- group by vendor
- editable permitted values before submission
- calculation preview
- gross/TDS/net totals
- submit

### 14.6 Approval Inbox

- pending approvals
- filters by amount/client/requester/date
- approve/reject/send back
- comments
- line-level decisions

### 14.7 Finance Queue

- approved lines grouped by vendor
- net payable
- TDS
- payment creation
- UTR/payment proof
- partial payment support

### 14.8 Vendor List and Vendor Detail

Vendor detail shows:
- contact details
- active vehicles
- trip history
- total freight
- advance paid
- cash paid
- TDS deducted
- unpaid/remaining amount
- unsettled trips
- recent messages
- documents

### 14.9 Vendor Ledger

Transaction-style view:
- date
- trip
- approval
- type
- gross
- TDS
- cash paid
- running operational balance where defined
- UTR
- status

### 14.10 Payment Register

- payment no
- vendor
- payment date
- gross allocated
- TDS
- net paid
- UTR
- approval batch
- trips count
- status

### 14.11 Reports

Minimum reports:
- Pending approvals
- Approved but unpaid
- Paid today/date range
- Vendor advance outstanding
- Vendor-wise business
- Vendor-wise payments
- TDS register
- Trip-wise cost and payment
- Trips completed but unsettled
- Advance paid but vehicle/trip cancelled
- POD pending
- NPL billing pending
- Trip profitability
- Vendor aging / unresolved balances

Exports: XLSX and CSV; PDF optional later.

### 14.12 Settings

- client master
- branch/cost center
- vehicle types
- charge types
- advance defaults
- TDS policies
- approval matrix
- notification templates
- Gmail connection
- WhatsApp connection
- user/role management

---

## 15. Search and Filters

Global search should support:
- trip no
- indent no
- vehicle number
- transporter/vendor
- driver name/phone where permitted
- UTR/reference
- approval number
- payment number

Most list screens need:
- date range
- status
- client
- branch
- vendor
- vehicle type
- approver
- finance status

---

## 16. Import Requirements

### 16.1 Legacy Excel import

Support the existing 17-column workbook format.

Import flow:
1. Upload XLSX.
2. Detect/match columns.
3. Preview normalized records.
4. Validate dates, money, transporter, vehicle, and required fields.
5. Show errors/warnings per row.
6. Option to create missing vendors/vehicles with review.
7. Import only after confirmation.
8. Store import job ID and original file.
9. Record source=IMPORT in audit log.

### 16.2 Duplicate checks

Warn on possible duplicate using combination of:
- date
- origin/destination
- vehicle number
- vendor
- amount
- NPL indent no when available

Do not silently merge duplicates.

---

## 17. Notification Rules

### In-app

Notify users for:
- approval assigned
- comment/@mention
- changes requested
- approval completed
- finance payment assigned/overdue if configured
- payment failed
- trip settlement pending

### Email

Configurable recipients for:
- approval request
- approval result
- finance queue
- payment completion

### WhatsApp

Transporter-facing only by default.

Notification sending must be queued, retryable, observable, and must not block the primary transaction.

---

## 18. Audit and Financial Controls

1. Approved monetary fields are locked.
2. Material change creates revision/re-approval.
3. Payment transaction cannot be deleted after PAID; use reversal/correction flow.
4. UTR/reference duplicate warning.
5. Payment amount cannot exceed remaining approved payable without privileged override and mandatory reason.
6. Vendor on HOLD cannot receive new payment approval without authorized override.
7. A transporter receives only its own data.
8. Finance payment allocation totals must equal the transaction totals.
9. Every TDS entry must link to a vendor and payment/trip context.
10. All protected changes are audited.
11. Approval and payment actions record user and timestamp.
12. Sensitive bank/contact data must not appear in debug/application logs.

---

## 19. Security Requirements

- Role-based access control enforced server-side.
- Object-level authorization for transporter/vendor-facing records.
- HTTP-only secure authentication cookies; do not store auth tokens in browser localStorage.
- CSRF protection as appropriate.
- Rate limiting for login, public links, and webhooks.
- Strong password policy and optional MFA-ready architecture.
- Encryption for integration refresh tokens and bank details at rest/application layer as feasible.
- HTTPS-only production deployment.
- Secret management through environment/secret store, never source control.
- Webhook signature/token validation.
- File upload validation, type/size limits, malware scanning hook-ready design.
- Audit log retention policy.
- Daily automated backups and documented restore process.

---

## 20. Non-Functional Requirements

### Performance

For normal company-scale usage:
- common list/detail APIs should target sub-second server response under typical load
- dashboard queries should use indexed aggregates/materialized summaries if needed
- imports and external notifications run asynchronously

### Reliability

- payment/approval writes use database transactions
- webhook processing idempotent
- retry queues for external integrations
- no duplicate payment allocation caused by retry

### Observability

- structured application logs
- request/correlation IDs
- background job status
- integration error dashboard
- health/readiness endpoints

### Accessibility / UX

- responsive desktop/mobile web UI
- keyboard-friendly table/forms where practical
- clear financial number formatting
- dates displayed in organization timezone
- no reliance on color alone for status

---

## 21. Proposed Technical Architecture

### Frontend

- Next.js + React + TypeScript
- Tailwind CSS
- accessible component library such as shadcn/ui or equivalent
- TanStack Query for server data state
- robust table/grid solution supporting filters, pagination, selection, and export actions

### Backend

- Django
- Django REST Framework
- PostgreSQL
- Celery + Redis for asynchronous jobs

### Storage

- S3-compatible object storage for documents
- local S3-compatible service such as MinIO may be used for development

### Integrations

- Gmail API + Google OAuth
- Google Cloud Pub/Sub for Gmail mailbox change notifications
- WhatsApp Business Cloud API + webhooks

### Deployment

- Dockerized services
- reverse proxy / managed platform
- separate dev/staging/production configuration

Use current stable compatible package versions at implementation time and lock them in project lockfiles.

---

## 22. Suggested API Areas

Illustrative REST paths:

```text
/api/auth/*
/api/users/*
/api/clients/*
/api/vendors/*
/api/vehicles/*
/api/drivers/*
/api/indents/*
/api/trips/*
/api/trips/{id}/charges/*
/api/approval-batches/*
/api/approval-batches/{id}/submit
/api/approval-batches/{id}/actions
/api/approval-batches/{id}/comments
/api/finance/pending
/api/payments/*
/api/vendor-ledger/*
/api/tds/*
/api/reports/*
/api/imports/excel/*
/api/integrations/gmail/*
/api/integrations/whatsapp/*
/api/webhooks/gmail/*
/api/webhooks/whatsapp/*
```

API design may evolve, but business invariants must remain server-side.

---

## 23. State Models

### Trip status

```text
DRAFT
READY
ADVANCE_APPROVAL_PENDING
ADVANCE_APPROVED
ADVANCE_PARTIALLY_PAID
ADVANCE_PAID
DEPLOYED
IN_TRANSIT
DELIVERED
SETTLEMENT_PENDING
SETTLEMENT_APPROVAL_PENDING
SETTLED
CANCELLED
CANCELLED_WITH_PAYMENT
```

### Approval status

```text
DRAFT
PENDING
CHANGES_REQUESTED
PARTIALLY_APPROVED
APPROVED
REJECTED
CANCELLED
SUPERSEDED
```

### Payment status

```text
DRAFT
PROCESSING
PAID
FAILED
REVERSED
```

Do not infer a trip's entire lifecycle from one status field. Approval/payment/settlement statuses should remain explicit.

---

## 24. Critical Validation Rules

A trip cannot enter approval if it lacks:
- client
- origin
- destination
- deployment date
- vendor
- vehicle number
- vendor freight rate

Submission validations:
- advance percent within configured limit unless override
- all money >= 0 except explicit deductions
- TDS policy resolved
- net requested cannot be negative unless special adjustment workflow
- vendor not blocked or valid override exists

Payment validations:
- payment vendor matches all allocations
- only approved items can be allocated
- allocation does not exceed remaining approved amount
- allocation sum equals transaction amount
- UTR/reference required for applicable payment modes

Settlement validations:
- final cost components saved
- all paid allocations included
- required POD/vendor invoice documents present if policy requires them

---

## 25. Reporting Definitions

### Vendor Advance Outstanding

Operational metric; must clearly define whether it represents:
- cash advances paid against trips not yet settled, or
- remaining cash payable to vendor.

Provide separate metrics to avoid ambiguity:

- **Advance Cash Paid, Unsettled:** cash paid on trips not yet settled.
- **Remaining Vendor Cash Payable:** final net vendor payable minus cash paid.

### Approved Not Paid

Sum of approved net amounts less payment allocations marked paid.

### Trip Profit

Client billing amount minus final vendor gross cost minus tracked internal trip costs.

TDS must not reduce vendor economic cost for margin calculation; it is withholding from cash paid.

---

## 26. MVP Acceptance Criteria

The MVP is accepted when all of the following work end-to-end:

1. Admin can create users/roles, NPL client, vendors, vehicles, and TDS/approval settings.
2. Operations can create a trip using all legacy Excel fields plus new control fields.
3. System calculates 90% advance by default.
4. System calculates 1% TDS using the configured policy and displays gross/TDS/net clearly.
5. Operations can select multiple trips and create one approval batch.
6. Approver can comment, attach a document, request changes, reject, or approve.
7. Approved items automatically appear in finance queue grouped by vendor.
8. Finance can create a vendor payment, record UTR/payment proof, and allocate it to trips.
9. Trip and vendor ledgers update immediately.
10. A paid transaction cannot be silently edited/deleted.
11. Material approved-cost changes trigger re-approval.
12. Transporter notification contains only that vendor's own trip/payment data.
13. Gmail can send approval emails and inbound replies can be associated with an approval thread.
14. WhatsApp integration can send configured transporter messages and record provider status/webhook events.
15. Dashboard shows pending approvals, approved-not-paid, paid, unsettled trips, vendor advances, and TDS.
16. Existing 17-column Excel format can be imported with preview and validation.
17. Audit history can answer who changed/approved/paid what and when.
18. Automated tests cover core calculation, authorization, approval, payment allocation, and webhook idempotency rules.

---

## 27. Example End-to-End Scenario

Example only; values are illustrative.

```text
Client: NPL
Trip: NPL-2026-000123
Route: Sonipat -> Ghaziabad
Vendor freight rate: INR 50,000
Advance percent: 90%
Freight advance gross: INR 45,000
Unloading advance: INR 2,500
Gross requested: INR 47,500
TDS rate: 1%
TDS amount: determined by configured TDS basis
Net requested: Gross requested - TDS this payment
```

Operations submits the trip in an approval batch. The manager asks a question in the approval thread, Operations responds with an attachment, and the manager approves. The vendor receives only their own approval notification. Finance sees the approved item in the vendor's payment queue, records the payment and UTR, and the vendor receives payment confirmation. The trip ledger now shows the approved gross amount, TDS withheld, cash paid, and remaining settlement exposure.

After delivery, Operations enters final cost adjustments and uploads POD/vendor invoice. The system computes remaining net payable, creates a final settlement approval if necessary, and closes the trip after the required settlement and NPL billing steps are complete.

---

## 28. Future Enhancements

- Full transporter portal with login
- Vendor self-service invoice/POD upload
- Bank API/payout integration
- OCR extraction from vendor invoices/PODs
- Vehicle GPS integration
- SLA/escalation engine
- Automatic rate cards and route/vendor rate suggestions
- Vendor scorecards
- Vendor document expiry/KYC
- Client receivables tracking
- Mobile/PWA deployment app
- Approval via secure email/WhatsApp action links where security policy permits
- Accounting/ERP integration

---

## 29. Product Principles

1. **Trip-first traceability:** Every payable must be traceable to a trip.
2. **Vendor isolation:** A transporter never sees another transporter's data.
3. **Approval before payment:** Finance cannot pay an unapproved request without controlled override.
4. **No silent financial edits:** Material changes are revisioned and audited.
5. **TDS is transparent:** Always show base, rate, amount, and cumulative deduction.
6. **Email/WhatsApp are channels, not the system of record:** The web application remains authoritative.
7. **Excel compatibility matters:** Existing spreadsheets should be easy to import/export during transition.
8. **Finance truth is allocation-based:** A bank payment may cover many trips, but every rupee must be allocated.

