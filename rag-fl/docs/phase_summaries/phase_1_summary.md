# Phase 1 Summary
> Auto-generated at end of phase. Save to docs/phase_summaries/phase_1_summary.md

---

## Phase 1 — Docker Infrastructure
**Completed:** 2026-03-05
**Status:** ✅ Complete

---

## 1. Files Created

| File | Description |
|---|---|
| `docker-compose.yml` | 5 infra services: mongo (rs0), redis, fake-gcs, libreoffice, mongo-express |
| `infra/mongo-init/init.sh` | Bash: waits for mongod → initiates rs0 → waits for PRIMARY → runs collections.js |
| `infra/mongo-init/collections.js` | Creates 5 collections + all indexes against ragfl database |
| `.env.example` | All required environment variables documented with comments |
| `Makefile` | `make up / down / logs / reset / ps / mongo-shell / init-gcs / test-infra` |
| `shared/__init__.py` | Package marker |
| `shared/utils/__init__.py` | Package marker |
| `shared/utils/vector_search.py` | Env-aware vector search: local cosine similarity (dev) vs Atlas `$vectorSearch` (prod) |
| `docs/phase_summaries/phase_1_summary.md` | This file |

---

## 2. How to Verify

```bash
# Start all infrastructure containers
make up
# Expected: all 5 containers start, mongo-init runs and exits cleanly

# Check container health
docker compose ps
# Expected:
# ragfl-mongo          Up (healthy)
# ragfl-redis          Up (healthy)
# ragfl-fake-gcs       Up
# ragfl-libreoffice    Up
# ragfl-mongo-express  Up

# MongoDB: confirm replica set PRIMARY
docker compose exec mongo mongosh --quiet --eval "rs.status().myState" ragfl
# Expected output: 1

# MongoDB: confirm all 5 collections
docker compose exec mongo mongosh --quiet --eval "db.getCollectionNames().sort().join(', ')" ragfl
# Expected output: citation_cache, doc_embeddings, documents, file_ledger, page_profiles

# Redis: basic connectivity
docker compose exec redis redis-cli ping
# Expected output: PONG

# fake-gcs: list buckets
curl -s http://localhost:4443/storage/v1/b
# Expected: JSON object containing "rag-fl-documents" bucket

# Gotenberg/LibreOffice: health check
curl -s http://localhost:3000/health
# Expected: {"status":"up","details":{"libreoffice":{"status":"up",...}}}

# Mongo Express UI
# Open http://localhost:8081 in browser → ragfl database visible with 5 collections
```

---

## 3. Test Results

| Test | Input | Expected | Actual | Pass? |
|---|---|---|---|---|
| MongoDB RS state | `rs.status().myState` | `1` (PRIMARY) | `1` | ✅ |
| MongoDB collections | `getCollectionNames()` | 5 collections | `citation_cache, doc_embeddings, documents, file_ledger, page_profiles` | ✅ |
| MongoDB healthcheck | `docker compose ps` | `(healthy)` | `(healthy)` | ✅ |
| Redis ping | `redis-cli ping` | `PONG` | `PONG` | ✅ |
| Redis healthcheck | `docker compose ps` | `(healthy)` | `(healthy)` | ✅ |
| fake-gcs bucket | GET `/storage/v1/b` | `rag-fl-documents` present | Present | ✅ |
| Gotenberg health | GET `/health` | `status: up`, `libreoffice: up` | Both up | ✅ |
| Mongo Express UI | Browser `localhost:8081` | ragfl db + 5 collections | Visible | ✅ |

---

## 4. Gemini API Usage

Not applicable — Phase 1 is infrastructure only. No API calls made.

---

## 5. Deviations from ARCHITECTURE.md

| Decision | ARCHITECTURE.md says | What was implemented | Reason |
|---|---|---|---|
| LibreOffice service | "LibreOffice headless" (generic) | `gotenberg/gotenberg:8` | Gotenberg wraps LibreOffice in a production-ready REST API on port 3000, matching `LIBREOFFICE_URL=http://libreoffice:3000` in `.env` |
| GCS bucket creation | Not specified in Phase 1 | `make init-gcs` (host-side curl, separate step) | `mongo:7.0` container has no curl/python; bucket creation must run from host after `make up` |
| `wiredTigerCacheSizeGB` | 2 GB memory limit (container) | Set to `1` GB (half the container limit) | Leaves headroom; WiredTiger cache + other mongod memory = 2 GB container ceiling |

---

## 6. Known Limitations / TODOs

- [ ] `make` requires GNU make — not installed on Windows by default. Run from Git Bash or WSL2. Alternative: call `docker compose` commands directly.
- [ ] GCS bucket must be created manually after first `make up` by running `make init-gcs`. Subsequent `make up` calls skip this (bucket persists in `gcs_data` Docker volume).
- [ ] Application services (`ingestion`, `file-ledger`, `page-analyzer`, `rag-fl`, `citation-engine`, `search-api`) are not yet in `docker-compose.yml` — each is added as its Phase is implemented.
- [ ] Atlas `$vectorSearch` index (768-dim, cosine) must be created manually via Atlas UI when migrating to production. Field: `embedding`, Index name: `embedding_index`.

---

## 7. Prerequisites for Phase 2

Before starting Phase 2 (Format Registry & Ingestion Service), verify:

- [ ] `make up` → all 5 containers start without error
- [ ] `ragfl-mongo` shows `(healthy)` in `docker compose ps`
- [ ] `ragfl-redis` shows `(healthy)` in `docker compose ps`
- [ ] All 5 collections present in the `ragfl` database
- [ ] `ragfl-fake-gcs` up on port 4443
- [ ] `ragfl-libreoffice` (Gotenberg) up on port 3000 with `libreoffice: up` in health response

```bash
# Run this to confirm ready for Phase 2:
docker compose exec mongo mongosh --quiet --eval "db.getCollectionNames().sort().join(', ')" ragfl
# Must return: citation_cache, doc_embeddings, documents, file_ledger, page_profiles
```
