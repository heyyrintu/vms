# Drona Logitech Transport Operations

A trip-first Drona Logitech operations system for deployments, advance approvals, vendor-specific finance payments, TDS, and auditable trip/vendor ledgers.

## Quick start (Docker)

1. Copy `.env.example` to `.env` and replace all placeholder secrets.
2. Run `docker compose up --build`.
3. Open `http://localhost:3000`.

The demo seed creates role-specific synthetic accounts. In local development the password is `ChangeMe123!`; replace it before any shared deployment.

| Role | Username |
|---|---|
| Operations | `operations` |
| Approver | `approver` |
| Finance | `finance` |
| Management | `management` |
| Admin | `admin` |

## Local development without Docker

Backend defaults to SQLite when `DATABASE_URL` is absent:

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py seed_demo
.venv\Scripts\python manage.py runserver
```

Frontend:

```powershell
cd apps/web
npm install
npm run dev
```

## Quality checks

```powershell
cd apps/api; pytest; ruff check .; python manage.py spectacular --file schema.yml --validate --fail-on-warn
cd apps/web; npm run lint; npm run typecheck; npm run build; npm run test:e2e
```

Browser tests expect the API on port 8000, the web app on port 3000, and seeded demo users. `E2E_BASE_URL` can target another web port. The authenticated load smoke is `python infra/load_smoke.py`.

For Coolify production, deploy the standalone `docker-compose.coolify.yml` definition
and follow [the Coolify production runbook](docs/coolify.md). For other production
targets, see `docs/deployment.md`; integration setup and implementation coverage are
documented in `docs/integrations.md` and `docs/implementation-status.md`.
