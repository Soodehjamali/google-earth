# Deployment Guide

Production deployment for the Agricultural Intelligence Platform.
The repository ships a Docker Compose based deployment model; no cloud
provider is assumed. Any host with Docker and Docker Compose v2 can run it.

## Architecture

```text
            ┌──────────────────────────────────────────┐
 client ──► │ frontend (nginx, static SPA + /api proxy) │
            └───────────────┬──────────────────────────┘
                            │ /api/*
            ┌───────────────▼──────────────────────────┐
            │ backend (FastAPI / uvicorn, 2 workers)    │
            └───────┬──────────────────────┬───────────┘
                    │                      │ outbound HTTPS
            ┌───────▼───────┐      ┌───────▼────────────┐
            │ PostgreSQL 15 │      │ Google Earth Engine │
            └───────────────┘      └────────────────────┘
```

- `frontend` is the only published port (`FRONTEND_PORT`, default 80).
- `backend` and `postgres` are internal to the compose network.
- The backend applies Alembic migrations on container start, then serves.

## Prerequisites

- Docker + Docker Compose v2
- A strong `POSTGRES_PASSWORD`
- Google Earth Engine service-account key (see `docs/EARTH_ENGINE_SETUP.md`)

## Configuration

```bash
cp .env.example .env   # fill in real values — never commit .env
```

Required production variables:

| Variable | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | Database password (no default — startup fails without it) |
| `CORS_ORIGINS` | JSON list of allowed frontend origins, e.g. `["https://agri.example.com"]` |
| `EE_PROJECT_ID` | GCP project registered for Earth Engine |
| `EE_SERVICE_ACCOUNT` | Service-account email |
| `EE_PRIVATE_KEY_FILE` | Key path **inside** the container (`/app/credentials/gee-key.json`) |
| `EE_KEY_MOUNT_DIR` | Host directory holding the key file, mounted read-only |

Optional: `POSTGRES_USER`, `POSTGRES_DB`, `LOG_LEVEL`, `CACHE_TTL`, `FRONTEND_PORT`.

### Fail-fast configuration validation

With `APP_ENV=production` the backend **refuses to start** if:

- `APP_DEBUG=true`
- `DATABASE_URL` contains development default credentials (`postgres:postgres*`)
- `CORS_ORIGINS` contains `*`

Interactive API docs (`/docs`, `/redoc`, `/openapi.json`) are disabled in
production automatically.

## Deploy

```bash
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
docker compose -f docker-compose.prod.yml ps        # all services healthy
```

Verify:

```bash
curl http://localhost/api/v1/health          # liveness
curl http://localhost/api/v1/health/ready    # readiness (checks database)
curl http://localhost/                        # frontend SPA
```

Stop gracefully:

```bash
docker compose -f docker-compose.prod.yml down
```

The backend disposes its database connection pool on shutdown.

## Health endpoints

| Endpoint | Type | Failure behaviour |
|---|---|---|
| `GET /api/v1/health` | Liveness | process up |
| `GET /api/v1/health/ready` | Readiness | 503 when the database is unreachable |
| `GET /api/v1/health/earth-engine` | Dependency status | reports GEE status; never blocks |

## Database operations

- Migrations run automatically at backend startup (`alembic upgrade head`).
- Migration files are additive; existing data is preserved.
- Backup: `docker compose -f docker-compose.prod.yml exec postgres pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup.sql`
- Restore: `cat backup.sql | docker compose -f docker-compose.prod.yml exec -T postgres psql -U $POSTGRES_USER $POSTGRES_DB`
- The `postgres_data` named volume holds all persistent state — back it up before upgrades.

## Secrets handling

- `.env`, `credentials/`, `*.pem`, `*.key` are git-ignored.
- `backend/.dockerignore` guarantees `.env` and `credentials/` are never
  baked into the backend image; the key file is mounted read-only at runtime.
- For higher-security deployments, store the key in a secrets manager and
  inject the file at runtime — the code only reads `EE_PRIVATE_KEY_FILE`.

## EXTERNAL EGRESS REQUIREMENT

Earth Engine requires outbound HTTPS from the backend host to:

- `earthengine.googleapis.com`
- `oauth2.googleapis.com`

This deployment does **not** bypass network restrictions. Real-world Earth
Engine acceptance (phase S.6) is **DEFERRED** and must be executed from a
network/egress path where these endpoints are reachable. Until then, the
`/api/v1/health/earth-engine` endpoint honestly reports the connectivity
status and the rest of the platform remains fully operational.

## Remaining infrastructure not provided by this repository

- TLS termination (put a TLS-terminating reverse proxy or load balancer in
  front of the frontend, or terminate TLS in nginx with your certificates)
- Log aggregation / metrics collection (the backend logs structured lines to
  stdout; ship them with your platform's tooling)
- Automated backup scheduling
