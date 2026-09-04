# Architecture

## Runtime shape

The system is a modular monolith. `apps/api` is the authoritative Django/DRF backend; `apps/web` is a Next.js client. PostgreSQL stores transactional data, Redis/Celery handles asynchronous work, and the object-storage boundary is S3 compatible. Docker Compose runs the local stack.

```text
Browser -> Next.js -> Django REST API -> PostgreSQL
                                |-----> Redis / Celery
                                |-----> S3-compatible storage
                                |-----> SMTP / WhatsApp adapters
```

The Next.js rewrite keeps browser API calls same-origin. Authentication uses Django sessions in HTTP-only cookies with CSRF protection. Browser storage never contains auth tokens.

## Backend modules

- `accounts`: custom user, roles, and capability matrix.
- `core`: organization financial settings, encryption/file controls, structured logs, request IDs, and concurrency-safe numbering.
- `operations`: clients, vendors, fleet, drivers, indents, trips, charges, and documents.
- `approvals`: Decimal calculation engine, batches/items, immutable actions, comments, and revisions.
- `payments`: vendor-owned payment transactions, trip allocations, TDS, settlements, billing, and ledger read models.
- `audit`: append-only hash-chained audit events.
- `integrations`: encrypted notification outbox, templates/preferences, fake and production SMTP/WhatsApp providers, media ingestion, and webhook boundaries.
- `imports`: validated legacy XLSX preview, atomic commit, missing-master creation, transition export and import audit records.

## Financial integrity

Approval items snapshot all calculation inputs and outputs. A payment belongs to one vendor; every allocation links one approved item and its trip. Service-layer transactions lock approval rows, block over-allocation, reconcile gross = TDS + net, and create trip-linked TDS records. Paid records reject financial edits and deletion; correction is a full audited reversal.

Ledgers are read models derived from approval items and payment allocations rather than stored running balances.

Sequential approvals copy the matched rule and stages into immutable batch snapshots. Final settlements calculate cumulative cash/TDS from allocations, require configured clean documents, create a new approval, and close only after the settlement amount and client billing gates reconcile.
