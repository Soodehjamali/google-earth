# Agricultural Intelligence Platform — Architecture

## Overview

A production-quality agricultural decision-support system that receives GPS coordinates or field polygons and analyzes satellite imagery, vegetation indices, climate data, soil properties, water resources, and land cover using Google Earth Engine.

## Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Backend Framework | FastAPI | 0.115+ |
| Language | Python | 3.11+ |
| ORM | SQLAlchemy | 2.0+ |
| Migrations | Alembic | 1.13+ |
| Validation | Pydantic | 2.x |
| HTTP Client | httpx | 0.27+ |
| Database | PostgreSQL | 15+ |
| Remote Sensing | Google Earth Engine Python API | latest |
| Frontend Framework | React | 19.x |
| Language | TypeScript | 5.x |
| Build Tool | Vite | 6.x |
| Maps | MapLibre GL JS | 4.x |
| Charts | Recharts | 2.x |
| Package Manager | pnpm | 11.x |
| Containerization | Docker Compose | 2.x |

## System Architecture

```
┌──────────────────────────────────────────────────────┐
│                    Frontend (React)                    │
│  ┌─────────────┬─────────────┬─────────────────────┐ │
│  │   MapLibre   │   Recharts  │   Dashboard UI      │ │
│  │   (Maps)     │   (Charts)  │   (KPIs, Reports)   │ │
│  └──────┬──────┴──────┬──────┴──────────┬──────────┘ │
│         │              │                 │             │
│         └──────────────┼─────────────────┘             │
│                        │ HTTP/REST                    │
└────────────────────────┼──────────────────────────────┘
                         │
┌────────────────────────┼──────────────────────────────┐
│                  Backend (FastAPI)                      │
│  ┌─────────────────────┴────────────────────────────┐ │
│  │              API Layer (v1)                       │ │
│  │  /locations  /analyses  /vegetation  /climate    │ │
│  │  /soil  /water  /landcover  /stress  /maps      │ │
│  └─────────────────────┬────────────────────────────┘ │
│                        │                               │
│  ┌─────────────────────┴────────────────────────────┐ │
│  │              Service Layer                        │ │
│  │  vegetation_service  climate_service              │ │
│  │  soil_service  water_service                      │ │
│  │  analysis_service  cache_service                  │ │
│  └─────────────────────┬────────────────────────────┘ │
│                        │                               │
│  ┌─────────────────────┴────────────────────────────┐ │
│  │        Earth Engine Service Layer                  │ │
│  │  client.py  datasets.py  indices.py               │ │
│  │  preprocessing.py  reducers.py  statistics.py     │ │
│  └─────────────────────┬────────────────────────────┘ │
│                        │                               │
│  ┌─────────────────────┴────────────────────────────┐ │
│  │              Data Layer                            │ │
│  │  PostgreSQL (SQLAlchemy 2.x)                       │ │
│  │  Redis (caching, optional)                         │ │
│  └──────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────┘
                         │
┌────────────────────────┼──────────────────────────────┐
│              Google Earth Engine                        │
│  Sentinel-2 SR  │  ERA5  │  MODIS  │  SoilGrids       │
└────────────────────────────────────────────────────────┘
```

## Data Flow

### Analysis Pipeline

```
Input Geometry (Point/Polygon)
    ↓
Validation (Pydantic)
    ↓
Geometry Processing (centroid, area, bbox)
    ↓
Dataset Selection (based on analysis_type)
    ↓
Date Filtering
    ↓
Cloud Filtering (scene-level)
    ↓
Cloud Masking (SCL/QA60)
    ↓
Band Selection & Rescaling
    ↓
Index Calculation (NDVI, EVI, SAVI, NDWI)
    ↓
Spatial Reduction (reduceRegion)
    ↓
Temporal Aggregation (reduceCollection)
    ↓
Statistics (mean, median, std, percentiles)
    ↓
Cache (Redis/in-memory)
    ↓
API Response (JSON)
    ↓
Frontend Visualization (Map + Charts + KPIs)
```

## Authentication

### Google Earth Engine

Two modes supported:

1. **Development**: Interactive `ee.Authenticate()` — generates token stored in `~/.earthengine/credentials`
2. **Production**: Service account with JSON key file

```python
# Production auth
ee.Initialize(
    credentials=ee.ServiceAccountCredentials(
        email=service_account_email,
        key_file=key_file_path
    ),
    project=project_id
)
```

### Security

- Frontend NEVER receives Earth Engine credentials
- All EE operations happen server-side
- API keys and tokens stored in `.env`, never committed to Git
- CORS restricted to configured origins

## Database Schema

### ER Diagram (Conceptual)

```
Location ──1:N──> Analysis ──1:N──> DatasetUsage
                                    │
                    Analysis ──1:N──> TimeSeries
                    Analysis ──1:N──> Report
```

### Models

- **Location**: UUID PK, name, geometry (GeoJSON), lat/lng, area, timestamps
- **Analysis**: UUID PK, FK→Location, date range, type, status, timestamps, error
- **DatasetUsage**: UUID PK, FK→Analysis, dataset_id, variable, resolution, date_range, metadata (JSONB)
- **TimeSeries**: UUID PK, FK→Analysis, date, variable, value, metadata
- **Report**: UUID PK, FK→Analysis, file_path, timestamps

## Caching Strategy

Cache key components:
```
geometry_hash + dataset_id + date_range + analysis_type + temporal_resolution + parameters
```

Cache targets:
- Image metadata
- Spatial statistics
- Time series data
- Map tile metadata

## Error Handling

| Error Type | HTTP Status | Frontend Display |
|-----------|-------------|-----------------|
| Invalid coordinates | 400 | مختصات نامعتبر |
| Invalid polygon | 400 | هندسه نامعتبر |
| Empty dataset | 204 | داده‌ای یافت نشد |
| EE auth failure | 503 | خطای احراز هویت |
| EE quota exceeded | 429 | سقف درخواست |
| Network error | 502 | خطای شبکه |
| Invalid dates | 400 | تاریخ نامعتبر |

## Testing Strategy

- **Unit**: Coordinate validation, polygon validation, index calculations, unit conversions, risk scoring, Pydantic schemas
- **Integration**: Earth Engine service (mocked when credentials unavailable), API endpoint testing
- **E2E**: Full analysis pipeline (requires EE credentials)

## Deployment

- Docker Compose for local development
- Services: frontend, backend, postgres, redis (optional)
- Environment variables via `.env` file
