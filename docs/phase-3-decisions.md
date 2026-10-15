# Phase 3: Frost Risk Module — Decisions Log

This document records architectural, agronomic, and operational decisions made during Phase 3 (Frost-risk advisory module). In accordance with the project instructions, when decisions are ambiguous, conservative and scientifically honest choices are selected and recorded here.

---

## Gate 0 Decisions

### G1. Credentials Discovery & Auto-Skip Marker
- **Decision:** Remove upward parent-directory traversal for credential discovery in production code (`backend/app/services/earth_engine/authentication.py`). Require explicit configuration via `EE_PRIVATE_KEY_FILE` (must be a valid, readable file path) or raw service account JSON via environment variables. Add a `requires_gee` pytest marker and fixture that automatically detects whether GEE credentials and initialization succeed; if not, tests marked with `@pytest.mark.requires_gee` are cleanly skipped with reason `"GEE credentials not configured or live EE unavailable"`.
- **Alternatives Considered:**
  1. Allowing fallback discovery in parent directories: Rejected because it breaks repo self-containment, risks accidental credential leakage if a parent directory is tracked or packaged, and violates production safety.
  2. Mocking all live GEE tests: Rejected because live integration tests verify real API communication with Google Earth Engine when credentials are provided.
- **Why:** Ensures clean-clone builds in isolated environments (e.g. CI/CD or outside the workspace tree) run without crashing while preserving live regression testing when credentials are supplied.

### G2. Removal of Embedded Development Identifiers
- **Decision:** Remove hardcoded postgres passwords (`postgres:postgres123`), real GEE project IDs (`proverbial-will-507706-e1`), and developer service account emails from fallback defaults in `config.py`. All sensitive settings must default to empty strings, `None`, or placeholder strings that require explicit environment injection or reading from `.env`.
- **Alternatives Considered:** Leaving local dev defaults in `config.py`. Rejected as insecure and bad hygiene.
- **Why:** Codebase must be completely clean of any secrets, project IDs, or service account emails in tracked code.

### G3. Secrets and Data Scan
- **Decision:** Strictly audit git tree and history for private keys, credentials, large JSON files, and uncommitted data samples. Untrack 10 large diagnostic JSON dumps (`backend/_a2_resp*.json` and `backend/_fa12_resp*.json`), and add `backend/_a2_*` to `.gitignore`. Scanned `git ls-files` to confirm zero credentials, private keys, or `.env` files are tracked. Conducted a full-history audit across all git branches (`git log -S "BEGIN PRIVATE KEY" --all`). Historical matches were found in early automated checkpoint stashes/commits (`9f3da4b`, `0ca7ebb`) before the repository audit. In strict accordance with the constraint "do not rewrite history (no reset/amend/rebase/force-push)", history was not rewritten, and all historical occurrences are documented and disclosed.
- **Why:** Complies with security cleanliness for current tracked tree while preserving immutable git history.

### G4. Tile Token Log Masking
- **Decision:** Mask both path-based tile tokens (`/api/v1/agriculture/tiles/{token}/...`) and query-string tokens (`?token=...`) across all logging formatters and filters.
- **Why:** Prevents credential/session leakage into access logs.

### G5. Frontend Test Suite Expectations
- **Decision:** Reconcile outdated assertion strings in legacy frontend tests to match the current localized (Persian) UI and modular architecture, without deleting or skipping tests. Document remaining exclusions if any.

### G6. Git Audit Documentation Correction
- **Decision:** Clarify in `docs/git-audit.md` that edits to pre-existing tests were swept up from earlier P-AGRI-1 / F-A12 work, and provide physical before/after SoilGrids values.
