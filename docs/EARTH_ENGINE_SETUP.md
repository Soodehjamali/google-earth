# Google Earth Engine — Backend Setup

This guide configures **server-side** access to Google Earth Engine for the
FastAPI backend using a **service account** and the official Python client
library (`earthengine-api`).

Credentials stay on the backend. They are **never** sent to the React
frontend, never stored in `localStorage`, and never returned by any API
endpoint. The only Earth Engine data the frontend receives is a safe status
payload from `GET /api/v1/health/earth-engine`.

> Status vocabulary used by the backend:
>
> - **Connected** — Earth Engine initialized and an authenticated request succeeded.
> - **Configuration Error** — `EE_PROJECT_ID` / credentials are missing or invalid.
> - **Disconnected** — configured, but Earth Engine rejected the request (permissions, registration, network, invalid credentials).

---

## 1. Prerequisites

| Item | Requirement | Notes |
|------|-------------|-------|
| Google account | Approved for Earth Engine (signed up / accepted the terms once) | One-time step for the account that owns the project |
| Google Cloud project | One project you can access | Used as the Earth Engine “registered project” |
| Billing | Not strictly required for Earth Engine data access, but required for many Cloud services | See Google Cloud billing docs |

Official references:

- Get started: <https://developers.google.com/earth-engine/guides/access>
- Authentication guide: <https://developers.google.com/earth-engine/guides/auth>
- Service accounts guide: <https://developers.google.com/earth-engine/guides/service_account>

---

## 2. Create or select a Google Cloud project

1. Open the Google Cloud Console: <https://console.cloud.google.com/>
2. In the project selector (top bar), choose an existing project or click
   **New Project**.
3. Note the **Project ID** (not the display name). Example: `agri-intel-42`.
   This value goes into `EE_PROJECT_ID`.

> Since early 2025 every Earth Engine request must come from a registered
> Cloud project. See the announcement on the Earth Engine forum if you are
> upgrading an older setup.

---

## 3. Register the project for Earth Engine

1. If you have never used Earth Engine with this account, sign up / accept the
   terms first at <https://code.earthengine.google.com/>.
2. Register your Cloud project for Earth Engine at
   <https://code.earthengine.google.com/register>. Follow the on-screen
   instructions and select the project from step 2.
3. Registration can take a few minutes to propagate.

---

## 4. Enable the Earth Engine API

1. In the Google Cloud Console go to **APIs & Services → Library**.
2. Search for **Google Earth Engine API**.
3. Select it and click **Enable**.

Reference (official troubleshooting): <https://developers.google.com/earth-engine/guides/auth>

> Symptom if skipped: `HttpError 403: Google Earth Engine API has not been
> used in project ...` (the health check reports *not enabled*).

---

## 5. Create a service account and download its key

A service account gives the backend a non-interactive identity.

1. In the Google Cloud Console go to **IAM & Admin → Service Accounts**.
2. Click **+ Create service account**.
3. Give it a name, e.g. `earth-engine-backend`.
4. **Grant this service account access to the project** — assign an IAM role
   (see the next section). If you skip it here you can add the role later via
   **IAM & Admin → IAM**.
5. Click **Done**.
6. In the service account list, open the new account → **Keys** tab →
   **Add key → Create new key** → choose **JSON** → **Create**. A JSON key
   file downloads automatically.

> The downloaded JSON contains the **private key**. Treat it like a password.

---

## 6. Assign the required IAM role

Open **IAM & Admin → IAM** in the Google Cloud Console, find the service
account, click the pencil (**Edit principal**) and add one of the roles below.

Official role definitions: <https://docs.cloud.google.com/iam/docs/roles-permissions/earthengine>
Access control guide: <https://developers.google.com/earth-engine/guides/access_control>

| Use case | IAM role | Role ID |
|----------|----------|---------|
| **Read public datasets and run computations (this project)** | **Earth Engine Resource Viewer** — minimum | `roles/earthengine.viewer` |
| The backend later writes/updates Earth Engine assets (e.g. export outputs) | Earth Engine Resource Writer | `roles/earthengine.writer` |
| Full Earth Engine resource management | Earth Engine Resource Admin | `roles/earthengine.admin` |

> A principal needs at least **Earth Engine Resource Viewer**
> (`roles/earthengine.viewer`) to make Earth Engine API calls through the
> Python client library. Granting more than needed is not recommended.

---

## 7. Store the key file securely

1. Create a credentials directory **inside the backend** (never inside a
   git-tracked location that gets committed):

   ```bash
   cd backend
   mkdir -p credentials
   # move the downloaded JSON there, e.g.:
   # mv ~/Downloads/your-project-xxxxxxxx.json credentials/service-account-key.json
   ```

2. Restrict permissions (Unix):

   ```bash
   chmod 600 credentials/service-account-key.json
   ```

3. Make sure `backend/credentials/` is ignored by git. Add to
   `backend/.gitignore` (or the repo root `.gitignore`) if not present:

   ```gitignore
   backend/credentials/
   backend/.env
   ```

4. **Never commit** `.env`, the key JSON, or any token to version control.

> For higher-security deployments, store the key in Google Secret Manager and
> mount/inject it instead of shipping the file — the code only reads the path
> given by `EE_PRIVATE_KEY_FILE`.

---

## 8. Configure the environment

1. Create `.env` from the template:

   ```bash
   cd backend
   cp .env.example .env
   ```

2. Fill in the Earth Engine variables:

   ```dotenv
   # --- Google Earth Engine ---
   # Cloud project ID registered for Earth Engine (step 2).
   EE_PROJECT_ID=agri-intel-42
   # client_email from the service-account key JSON (step 5).
   EE_SERVICE_ACCOUNT=earth-engine-backend@agri-intel-42.iam.gserviceaccount.com
   # Path to the key file, relative to backend/ (step 7).
   EE_PRIVATE_KEY_FILE=./credentials/service-account-key.json
   ```

   - `EE_SERVICE_ACCOUNT` must equal the `client_email` inside the key JSON.
   - `EE_PRIVATE_KEY_FILE` is resolved relative to where the backend process
     runs (the `backend/` directory).

The backend reads these through `backend/app/core/config.py`
(pydantic-settings). They can also be provided as real environment variables,
which is how the Docker Compose setup passes them.

---

## 9. Test the connection

### 9a. Start the backend

```bash
cd backend
python -m venv .venv                      # first time only
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install -r requirements.txt           # first time only
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

At startup the backend logs Earth Engine status:

```
INFO  Earth Engine ready — project: agri-intel-42
# or
WARNING  Earth Engine BLOCKED — EE_PROJECT_ID is not set — required: ...
```

### 9b. Health endpoint (recommended)

```bash
curl -s http://localhost:8000/api/v1/health/earth-engine
```

Expected success:

```json
{
  "status": "connected",
  "earth_engine": true,
  "authenticated": true,
  "project": "agri-intel-42",
  "checked_at": "2026-09-04T12:00:00+00:00"
}
```

Expected when credentials are not configured yet (honest — never faked):

```json
{
  "status": "error",
  "earth_engine": false,
  "authenticated": false,
  "code": "not_configured",
  "message": "Earth Engine is not configured. EE_PROJECT_ID is not set — required: a Google Cloud project ID that is registered for Earth Engine.",
  "checked_at": "2026-09-04T12:00:00+00:00"
}
```

### 9c. Inline Python check

```bash
cd backend
python -c "from app.services.earth_engine.authentication import get_earth_engine_health; import json; print(json.dumps(get_earth_engine_health(), indent=2))"
```

---

## 10. Troubleshooting

The `message` and `code` fields of the health endpoint map to these fixes:

| `code` | Meaning | Fix |
|--------|---------|-----|
| `not_configured` | No EE environment variables set | Fill in `EE_PROJECT_ID` (and, for production, the service account vars) in `backend/.env` |
| `invalid_configuration` | Env partially set, key file missing/malformed, or no developer credentials | Check `EE_SERVICE_ACCOUNT` + `EE_PRIVATE_KEY_FILE` and that the JSON key exists and is valid |
| `not_enabled` | “Google Earth Engine API has not been used in project …” | Enable **Google Earth Engine API** in APIs & Services → Library (step 4) |
| `not_registered` | Project not registered / not found | Register the project: <https://code.earthengine.google.com/register>; verify `EE_PROJECT_ID` spelling |
| `permission_denied` | Service account lacks Earth Engine access | Grant `roles/earthengine.viewer` (step 6); wait a few minutes for IAM propagation |
| `auth_failed` | Credentials rejected (`invalid_grant`) or none found | `EE_SERVICE_ACCOUNT` must match the key JSON `client_email`; check server clock (NTP); re-download the key if rotated |
| `connection_failed` | Unexpected / network error | Check backend logs and outbound access to `earthengine.googleapis.com` |

Other official references:

- Authentication and initialization: <https://developers.google.com/earth-engine/guides/auth>
- Python installation: <https://developers.google.com/earth-engine/guides/python_install>
- Service accounts: <https://developers.google.com/earth-engine/guides/service_account>

---

## 11. Security checklist

The backend must **never** expose, and the frontend must **never** receive:

- service-account private key
- client secret
- access / OAuth tokens
- credential JSON
- Earth Engine authentication credentials

- [x] Credentials are only read server-side (`backend/app/services/earth_engine/authentication.py`).
- [x] `GET /api/v1/health/earth-engine` returns status, project ID, timestamp only.
- [x] `.env` and `credentials/` are git-ignored; `.env.example` holds placeholders only.
- [x] The UI shows status/indicator only — never secrets (Dashboard indicator + Settings → Earth Engine).
