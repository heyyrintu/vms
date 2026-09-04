# Implementation status

Last updated: 2026-09-05

## Runnable vertical slice

- [x] Django/DRF + Next.js/TypeScript modular monorepo
- [x] PostgreSQL/Redis/Celery/MinIO Docker Compose foundation
- [x] Session-cookie authentication, CSRF, six roles, server-side capability checks
- [x] NPL client, vendor, contact/bank, vehicle, driver, indent, trip, charge and document models
- [x] Vendor/driver KYC uploads (Aadhaar, PAN and driving licence), encrypted vendor account numbers, IFSC validation and cancelled-cheque proof
- [x] Drona Logitech logo, red/orange visual identity and branded web, email, MFA and API surfaces
- [x] Human-readable concurrency-safe trip, approval and payment numbers
- [x] Decimal calculation service with 90% default and all four configurable TDS modes
- [x] Multi-trip/multi-vendor approval batch snapshots
- [x] Submit, approve all/selected, reject, send back, self-approval control and immutable actions
- [x] Context comments with internal/transporter visibility model
- [x] Vendor-grouped finance queue and one-vendor payment enforcement
- [x] Partial-payment service, overpayment checks, exact allocation reconciliation and UTR
- [x] Finance partial-allocation editor with per-trip gross/TDS/cash limits and remaining-balance carry-forward
- [x] Paid transaction/allocation/TDS immutability, audited reversal and balanced reversal ledgers
- [x] Trip/vendor ledger read models and TDS register
- [x] Finance due-diligence queue with vendor/driver KYC, trip documents, masked bank details and cancelled-cheque verification
- [x] Unified 100% freight, planned advance, freight balance, cash paid, TDS and remaining-to-pay tracking across dashboard, trips and vendor ledgers
- [x] Date-time rendering for event timestamps, with business dates paired to their created/paid/approved timestamps
- [x] Append-only hash-chained audit log and request correlation IDs
- [x] Dashboard and dense responsive operational UI
- [x] Paginated trip, indent, approval, vendor and payment registers with date/master/status filters and cross-field search
- [x] Exact 17-column Excel upload/normalization preview, serial dates, formula checks and duplicate warnings
- [x] Full indent/challan register with party, address, destination, item and quantity fields; timestamped Excel import and downloadable validated template
- [x] Multi-indent vehicle trips with backward-compatible primary indent, ranked add-to-trip suggestions and trip/payment trace links
- [x] SMTP/WhatsApp provider interfaces, fake provider, idempotent inbound records, email reference mapping, WhatsApp verification/signature checks
- [x] Synthetic seed, migrations, automated tests, CI, API schema and runbooks

## Completed PRD phases

- [x] Configurable amount/client/branch/purpose rules with sequential role stages, decision history and admin UI
- [x] Advance and settlement revision detection, supersession links, re-approval, immutable prior snapshots and visible revision diffs
- [x] Context documents, protected downloads, signature validation, optional ClamAV scanning and private S3 storage
- [x] Threaded comments, attachments, mentions, edit history and transporter-safe visibility enforcement
- [x] Reusable threaded discussion UI for trips and approvals, including replies, user mentions, visibility, attachments and controlled edits
- [x] Delivery, document gates, final settlement approval/payment, client billing and trip profitability/closure
- [x] Cancelled-after-payment recovery workflow
- [x] In-app notifications, per-user preferences, per-channel templates, encrypted transactional outbox and retry operations
- [x] Self-service notification preference matrix, template/rule activation controls and admin reconciliation for unmapped inbound replies
- [x] Approver and Finance email/WhatsApp alerts with editable staff contacts and authenticated return-to-action links
- [x] Encrypted SMTP delivery with STARTTLS/SSL, outbox retries and optional inbound email reconciliation webhook
- [x] WhatsApp Cloud API template/text send, signed webhook, reply/status mapping and validated private media ingestion
- [x] Interactive WhatsApp approval with branded trip PDF, document-template delivery, signed Approve/Reject buttons, sender/stage authorization and idempotent decisions
- [x] Live connection-aware WhatsApp/SMTP provider selection, Meta-compliant 128-character approval payloads and post-commit synchronous delivery for workerless local installs
- [x] Atomic Excel confirmation, missing-master creation, duplicate control and historical-format XLSX export
- [x] Fourteen paginated/filterable report families with totals and CSV/XLSX exports
- [x] Consolidated MIS register with past-trip/payment search, financial summaries, filtered XLSX export and admin-only historical record preview/posting
- [x] Password reset, TOTP MFA, throttling, encrypted bank/provider/outbox values and production security settings
- [x] Non-root containers, production Compose override, health/readiness, structured logs and backup/restore scripts
- [x] PostgreSQL sequence-race CI coverage, browser smoke tests, authenticated load smoke and secret scanning

## Verification status

- Backend: 65 collected tests; 64 pass locally and the PostgreSQL-only concurrency case runs in CI.
- API: OpenAPI generation validates with zero warnings.
- Frontend: ESLint, strict TypeScript and optimized Next.js build pass.
- Browser: Eight Chromium flows cover the prior UI smoke coverage plus a cross-role trip → approval → approver decision → partial finance payment workflow.
- Deployment security: `manage.py check --deploy` passes with production environment values.

Live SMTP, WhatsApp and object-storage calls require organization-owned credentials. Their production adapters, encrypted configuration, webhooks, retry paths and setup UI are complete; credential provisioning is intentionally an operator action.
