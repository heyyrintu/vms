# Coolify production runbook

This repository ships a dedicated production definition in `docker-compose.coolify.yml`.
It runs the public Next.js service plus private Django, Celery, PostgreSQL, Redis,
MinIO, and ClamAV services. Only `web` should receive a public domain.

## 1. Server and DNS

- Use a current Coolify server with at least 4 vCPU, 8 GB RAM, and enough SSD space
  for the database, uploaded documents, malware signatures, logs, and backup staging.
- Point the application hostname (for example `vms.yourcompany.com`) at the Coolify
  server before assigning the domain.
- Keep ports 5432, 6379, 8000, 9000, 9001, and 3310 closed publicly. Coolify's
  private Compose network carries this traffic.

ClamAV is the main memory consumer. If production load grows, move PostgreSQL and
object storage to managed services before reducing malware-scanning capacity.

## 2. Create the Coolify resource

1. Push the repository to the production Git provider.
2. In Coolify, create a resource from that repository and select **Docker Compose**.
3. Set the base directory to `/` and the Compose file to
   `/docker-compose.coolify.yml`.
4. Use normal (not Raw) Compose deployment so Coolify can generate its network,
   credentials, and proxy configuration.
5. In Advanced build settings, leave source-commit build-arg injection disabled to
   preserve Docker layer caching. The compose file supplies the only required web
   build argument.

Do not combine this file with `docker-compose.yml` or `docker-compose.prod.yml`.
Those files are retained for local development and non-Coolify deployments.

## 3. Configure variables

Use `.env.coolify.example` as the checklist, but enter values in Coolify rather than
committing a production `.env` file. Variables using the `${NAME:?message}` form are
required and Coolify will flag them when empty. The five `SERVICE_USER_*` and
`SERVICE_PASSWORD_*` values are Coolify magic variables and should be allowed to
generate once; do not regenerate them after data exists.

Generate the application secrets locally:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put the first value in `DJANGO_SECRET_KEY` and the second in
`FIELD_ENCRYPTION_KEY`. Set:

- `APP_HOST` to the hostname only, such as `vms.yourcompany.com`.
- `APP_URL` to the exact HTTPS origin, such as `https://vms.yourcompany.com`.
- SMTP credentials and a From address verified by the mail provider.
- A permanent Meta system-user token, WhatsApp phone-number ID, app secret, and a
  separately generated webhook verification token.
- The exact names and language codes of all Meta-approved templates. Template names
  are case-sensitive.

`FIELD_ENCRYPTION_KEY` protects stored provider/bank secrets. Changing it without a
controlled re-encryption migration makes existing encrypted data unreadable.

## 4. Domain and webhook routing

Assign this domain to the **web** service only:

```text
https://vms.yourcompany.com:3000
```

Coolify uses the port suffix to route public HTTPS traffic to port 3000 inside the
container; users still browse the normal URL without `:3000`. Do not assign domains
or publish ports for `api`, `postgres`, `redis`, `minio`, `clamav`, `worker`, `beat`,
`migrate`, or `minio-init`.

Configure provider callbacks through the public web origin:

- WhatsApp callback: `https://vms.yourcompany.com/api/webhooks/whatsapp/`
- Email inbound callback: `https://vms.yourcompany.com/api/webhooks/email/`

Use `WHATSAPP_VERIFY_TOKEN` in Meta's verification form. Meta POST requests are
validated with `WHATSAPP_APP_SECRET`; inbound email requests must send
`Authorization: Bearer <EMAIL_WEBHOOK_TOKEN>`.

## 5. First deployment

Deploy after every required variable is populated. The release flow is automatic:

1. PostgreSQL, Redis, MinIO, and ClamAV become healthy.
2. `minio-init` creates the private document bucket and enables object versioning.
3. `migrate` applies database migrations exactly once for the release.
4. Django runs `production_check`, including live PostgreSQL, Redis, MinIO, and
   ClamAV checks. It will refuse to start on placeholder/insecure configuration.
5. API, Celery worker/beat, and finally the web service become healthy.

The production stack intentionally never runs `seed_demo`.

For the first administrator, temporarily add these Coolify variables to the `api`
service environment and redeploy:

```text
BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_EMAIL=your-real-admin@yourcompany.com
BOOTSTRAP_ADMIN_PASSWORD=<unique password of at least 12 characters>
```

Open the `api` terminal and run:

```text
python manage.py bootstrap_admin
```

Then remove `BOOTSTRAP_ADMIN_PASSWORD` from Coolify and redeploy. Sign in, create the
real Operations, Approver, and Finance users, and give each one a real email address
and E.164 WhatsApp number such as `+919876543210`.

## 6. Go-live checks

Before accepting real records, verify all of the following:

- `https://vms.yourcompany.com/api/health/` returns `status: ok`.
- `https://vms.yourcompany.com/api/readiness/` returns `status: ready`.
- Admin login, logout, and a role-based login all work over HTTPS.
- A small test document uploads and downloads; an invalid file is rejected.
- An approval request reaches a real approver by SMTP and WhatsApp with its PDF.
- Approve and Reject WhatsApp quick replies reach the webhook and update the batch.
- Approval sends the Finance notification; payment completion reaches Operations.
- The integration outbox contains no failed or permanently queued test messages.
- Browser cookies are Secure and no browser request uses an HTTP origin.

Run a light staging smoke test before go-live:

```text
python infra/load_smoke.py --base-url https://staging-vms.yourcompany.com --requests 100 --concurrency 10
```

Do not run uncontrolled load tests against production.

## 7. Backups, updates, and rollback

- Configure Coolify's scheduled PostgreSQL backup for the `postgres` service and
  copy backups to an external S3-compatible destination. The Compose service uses
  the standard `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` variables so
  Coolify can resolve them.
- Back up the `minio_data` volume independently or replicate the bucket off-server.
  Bucket versioning protects against overwrites; it is not an off-server backup.
- Back up the generated Coolify credentials and application secrets in the company
  password manager.
- Perform and document a restore drill before go-live and at least quarterly.
- Deploy immutable Git commits/tags. Check migrations and backups before each release.
- For an application rollback, redeploy the previous commit only when its code is
  compatible with the migrated schema. If it is not, stop writers and restore the
  tested database and object-store recovery points together.

## 8. Routine monitoring

Alert on deployment health, HTTP 5xx rate, disk use, PostgreSQL backup failures,
Celery queue growth, failed integration outbox rows, and WhatsApp webhook failures.
Review SMTP and Meta token expiry/rotation procedures before the first live approval.
