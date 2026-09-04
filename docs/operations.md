# Operations runbook

## Local startup

Run `docker compose up --build`, then open `http://localhost:3000`. Compose applies migrations and runs the idempotent synthetic seed. Health and readiness are available at `/api/health/` and `/api/readiness/`.

## Demo workflow

1. Sign in as `operations`, create a trip, then build and submit an approval.
2. Sign in as `approver`, open the approval inbox, add a comment, and approve selected or all lines.
3. Sign in as `finance`, open Pending Payments, select lines inside one vendor group, enter the payment date and UTR, and record the payment.
4. Inspect the payment detail, vendor ledger, trip ledger, TDS register, and approval activity.
5. Mark a trip delivered, upload clean POD and vendor invoice documents, calculate/submit the final settlement, approve/pay its remaining line, record client billing, and close the trip.

When creating a vendor, enter the bank name, account holder, account number and IFSC, then attach the cancelled cheque. Aadhaar and PAN are optional identity-verification uploads. When creating a driver, Aadhaar, PAN and driving licence can be attached. These files are visible only to authorized internal roles; account numbers are never returned in full after saving.

All demo users initially use `ChangeMe123!`. Change credentials immediately in any shared environment.

For production notifications, an administrator must populate email and international-format WhatsApp numbers for Approver and Finance users under Settings. Approval requests include a secure link back to the exact approval; approved requests include a link to the Finance queue. Decisions are completed after authentication in the application, not by unauthenticated WhatsApp text.

## Production checklist

- Replace `DJANGO_SECRET_KEY` and all provider/object-storage placeholders.
- Set `DJANGO_DEBUG=false`, exact allowed hosts and trusted HTTPS origins.
- Use managed PostgreSQL, Redis and S3-compatible storage with backups.
- Run migrations before deploying application instances.
- Configure TLS, file malware scanning, log aggregation, Celery monitoring, and restore drills.
- Have finance approve the configured TDS policy and taxable basis before go-live.
- Configure SMTP and WhatsApp from the Integrations page and verify Celery is draining the outbox.
- Run `python manage.py spectacular --file schema.yml --validate --fail-on-warn` and `python manage.py check --deploy` in release CI.

## Routine operations

- Failed email/WhatsApp records remain in the outbox with retry count, next-attempt time and a minimized error. Administrators can retry immediately from Integrations.
- Inbound email/WhatsApp records without a reliable object mapping appear in the reconciliation queue; resolve them only after checking the referenced approval/trip/payment.
- Paid transactions are immutable. Use the finance reversal action with a reason; do not edit database rows.
- Approved financial trip fields require a reasoned revision and new approval. Historical snapshots/actions remain unchanged.
- Cancel a paid trip only with a recovery method and reason, then resolve the generated recovery record with an external reference.
- Imports are preview-only until confirmation. Missing masters, invalid rows and duplicate handling are explicit; the source workbook and confirmation result remain audited.

## MIS history and opening records

Open **Control → MIS records** to search past trips and reconcile the 100% vendor amount, approved amount, cash paid, TDS, approved balance, total remaining amount, payment number and UTR on one line. Filters cover date, transporter, trip state, payment state and a combined trip/indent/route/vehicle/UTR search. The filtered register can be exported to XLSX.

Administrators can migrate opening records from the same page:

1. Download `drona-mis-history-template.xlsx` and enter data only in the **MIS Records** sheet.
2. Use one row per trip/payment allocation. Repeat the trip for a second payment/UTR, keeping its approved financial values identical.
3. Preview the workbook and resolve reconciliation errors. `NET APPROVED` must equal `GROSS APPROVED - TDS APPROVED`; paid TDS plus paid cash cannot exceed the approved values.
4. Confirm the import. The transaction creates or reuses trip masters, posts an approved historical item, groups rows sharing a vendor/date/UTR into one payment, and creates trip allocations and TDS entries.

Confirmation is admin-only because it posts immutable financial history. The workbook hash makes repeat confirmation idempotent, existing trip/UTR allocations are skipped, and imported historical payments intentionally do not trigger old email or WhatsApp notices. The original workbook and import outcome remain in the import history and audit log.
