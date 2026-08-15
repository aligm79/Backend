# DMP Backend (AbroadPath API)

FastAPI backend for the AbroadPath study-abroad application platform. Python 3.12,
SQLAlchemy 2 (async) + PostgreSQL, Alembic migrations, JWT auth (admin + user
audiences), Argon2id password hashing, OTP login, and a modular monolith layout.

> Ported 1:1 from the original .NET backend — same routes, same `{ code, data, meta }`
> response envelope, same `X-Admin-Token` / `X-User-Token` headers, same database schema.

## Quick start (Docker)

```bash
docker compose up -d --build
```

That starts:

| Service  | URL                        | Notes                                  |
| -------- | -------------------------- | -------------------------------------- |
| API      | http://localhost:8000      | FastAPI (Swagger at `/docs`)           |
| Postgres | localhost:5433             | db `dmp_dev`, user/pass `postgres`      |
| Adminer  | http://localhost:8080      | DB UI                                  |

On first boot the API applies all Alembic migrations and seeds:

- The default super-admin (`admin` / `@Admin1234`)
- ~195 ISO countries with flag emojis
- The `university` catalog type + 2 sample subscription plans
- The 3 sample universities from `sample-data/` (Harvard, MIT, Stanford)

## Quick start (local dev, no Docker)

```bash
python -m venv .venv && . .venv/Scripts/activate    # Windows (source .venv/bin/activate on *nix)
pip install -e .
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/dmp_dev"
export JWT_SECRET_KEY="change-me-to-a-long-random-secret-at-least-32-bytes"
alembic upgrade head
uvicorn dmp.main:app --reload --port 8000
```

## Configuration (environment)

| Key | Purpose |
| --- | ------- |
| `DATABASE_URL` | Postgres DSN (`postgresql://user:pass@host:port/db`) |
| `JWT_SECRET_KEY` | HS256 signing key — must be ≥ 32 UTF-8 bytes |
| `DATABASE__AUTO_MIGRATE` | `true` to run `alembic upgrade head` on boot |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Seeded super-admin credentials |
| `UPLOADS_DIR` | Where application documents are stored |
| `DOCS_ENABLED` | `true` to serve Swagger UI at `/docs` |
| `BACKEND_CORS_ORIGINS` | JSON array or comma-separated allowed origins |

## Modules (`src/dmp/modules/`)

- **auth** — admin + user auth (email/password AND phone/email OTP), JWT issuing
- **billing** — subscription plans, Zarinpal payments (legacy marketplace)
- **catalog** — universities CRUD, countries, JSON import
- **applications** — study-abroad applications + document uploads (AbroadPath)
- **profile** — extended user profile + per-user settings

## Migrations

```bash
alembic upgrade head        # apply
alembic revision -m "..."   # create a new one (autogenerate diffs vs models)
```
