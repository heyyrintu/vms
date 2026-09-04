# Production deployment

> Deploying on Coolify? Use the dedicated, step-by-step
> [Coolify production runbook](coolify.md) and `docker-compose.coolify.yml`. The
> commands below apply to non-Coolify hosts.

## Required infrastructure

- PostgreSQL 17-compatible database with automated backups and point-in-time recovery.
- Redis for Celery broker/results.
- Private S3-compatible bucket with encryption, versioning and lifecycle rules.
- TLS-terminating reverse proxy forwarding `X-Forwarded-Proto`.
- Optional ClamAV `INSTREAM` endpoint; recommended for every shared deployment.
- SMTP relay and WhatsApp Business credentials when those channels are enabled.

Copy `.env.example` to the deployment secret store. Set a long random `DJANGO_SECRET_KEY`, a Fernet-compatible `FIELD_ENCRYPTION_KEY`, exact HTTPS hosts/origins, database/Redis URLs, and object-storage credentials. Production startup fails if either application encryption secret is missing.

## Release sequence

1. Build immutable images and run backend tests, OpenAPI validation, frontend lint/typecheck/build, and browser tests.
2. Back up PostgreSQL and confirm the object-store recovery point.
3. Run `docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm api python manage.py migrate --noinput` once.
4. Bootstrap the first administrator by putting a 12+ character value in `BOOTSTRAP_ADMIN_PASSWORD`, then run `docker compose ... run --rm api python manage.py bootstrap_admin --username <name> --email <address>`.
5. Start with `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`.
6. Verify `/api/health/`, `/api/readiness/`, a login, one protected API call, Celery worker/beat health, storage upload/download and outbox delivery.

Do not run `seed_demo` in production. Apply schema migrations before deploying application instances that require them. Roll back application images only when the migrated schema remains compatible; otherwise restore the tested pre-release database and object-store recovery point.

## Backup and restore

Run `powershell -File infra/backup.ps1 -OutputDirectory <approved-backup-directory>`. The SQL contains clean/idempotent object statements. Store it encrypted and pair it with the matching versioned S3 recovery point.

For a restore, stop API/worker/beat writers, verify the exact backup path, then run `powershell -File infra/restore.ps1 -BackupFile <absolute-sql-path> -ConfirmRestore`. Restart services, run readiness, audit-chain verification and financial reconciliation checks. Exercise this procedure on a non-production database regularly.

## Security and operations

- Keep `DJANGO_DEBUG=false`; cookies are Secure/HTTP-only and HSTS/SSL redirect are enabled in this mode.
- Rotate provider and object-storage secrets through the secret manager. Rotation of `FIELD_ENCRYPTION_KEY` requires a controlled data re-encryption procedure.
- Restrict webhook routes at the edge where possible; configure email bearer verification and Meta app-secret signatures.
- Forward JSON logs to centralized storage and alert on HTTP 5xx, failed outbox records, queue backlog and readiness failures.
- Run `python manage.py check --deploy` using the exact deployment environment before release.
- Run `python infra/load_smoke.py --base-url https://<host> --requests 100 --concurrency 10` against staging, never uncontrolled against production.
