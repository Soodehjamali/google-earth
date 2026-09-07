# Development Guide

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ | Backend runtime |
| Node.js | 18+ | Frontend runtime |
| pnpm | 8+ | Frontend package manager |
| Docker | 20+ | Database and services |
| Docker Compose | 2.0+ | Multi-service orchestration |
| PostgreSQL | 15+ | Database |
| Google Earth Engine Account | — | Required for satellite data |

## Quick Start

### 1. Clone & Setup

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Frontend
cd frontend
pnpm install
```

### 2. Environment Configuration

```bash
cp .env.example .env
# Edit .env with your configuration
```

### 3. Start Services

```bash
# Database (via Docker)
docker-compose up -d postgres

# Backend
cd backend
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
pnpm dev
```

### 4. Google Earth Engine Authentication

Credentials are configured **server-side only** (never in the browser).
Follow the full step-by-step guide in `EARTH_ENGINE_SETUP.md` (Google Cloud
project registration, Earth Engine API enablement, service account + IAM
roles, key storage).

Quick configuration in `backend/.env`:

```bash
EE_PROJECT_ID=your-project-id
EE_SERVICE_ACCOUNT=your-service-account@project.iam.gserviceaccount.com
EE_PRIVATE_KEY_FILE=path/to/key.json
```

Verify the connection:

```bash
curl http://localhost:8000/api/v1/health/earth-engine
```

## Project Structure

See `ARCHITECTURE.md` for the full system architecture.

## Backend Development

### Running Tests

```bash
cd backend
pytest -v
pytest tests/unit/ -v      # Unit tests only
pytest tests/integration/ -v  # Integration tests
```

### Database Migrations

```bash
cd backend
alembic revision --autogenerate -m "description"  # Create migration
alembic upgrade head                                # Apply migrations
alembic downgrade -1                                # Rollback one step
```

### API Documentation

Start the backend and visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Frontend Development

### Development Server

```bash
cd frontend
pnpm dev        # Start dev server on port 5173
pnpm build      # Production build
pnpm preview    # Preview production build
```

### Linting & Type Checking

```bash
cd frontend
pnpm lint       # Run ESLint
pnpm tsc --noEmit  # TypeScript check
```

## Docker

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f backend
docker-compose logs -f frontend

# Stop all services
docker-compose down
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| APP_ENV | No | development | Application environment |
| DATABASE_URL | Yes | — | PostgreSQL connection string |
| EE_PROJECT_ID | Yes | — | Google Earth Engine project ID |
| EE_SERVICE_ACCOUNT | No | — | Service account email |
| EE_PRIVATE_KEY_FILE | No | — | Path to service account key |
| REDIS_URL | No | — | Redis connection string (optional) |
| CORS_ORIGINS | No | http://localhost:5173 | Allowed CORS origins |

## Coding Standards

### Python
- Follow PEP 8
- Use type hints
- Docstrings for public functions
- Pydantic models for API schemas

### TypeScript
- Strict mode enabled
- Interface-first design
- Component-based architecture
- CSS modules or Tailwind for styling

## Troubleshooting

### Earth Engine Authentication Error
```
EEException: Not authenticated: Run `earthengine authenticate`
```
Solution: Run `earthengine authenticate` or configure service account in `.env`

### Database Connection Error
```
OperationalError: could not connect to server
```
Solution: Ensure PostgreSQL is running via `docker-compose up -d postgres`

### Frontend Build Error
```
Module not found
```
Solution: Run `pnpm install` in the frontend directory
