# ─────────────────────────────────────────────────────────────────────────────
# Makefile — rag-fl local development commands
# Requires: Docker Desktop (WSL2 backend), docker compose V2 plugin
# Run from: E:\Work\TMC - Roshn\Work\Embedding Projects POC\code\rag-fl
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: up down logs reset mongo-shell redis-shell init-gcs test-infra ps help

# ── Core lifecycle ────────────────────────────────────────────────────────────

## Start all infra containers in detached mode
up:
	docker compose up -d
	@echo ""
	@echo "Containers started. Waiting for MongoDB PRIMARY (up to 60s)..."
	@docker compose logs -f --no-color mongo-init 2>&1 | head -80 || true
	@echo ""
	@echo "Creating GCS bucket..."
	@curl -s -X POST http://localhost:4443/storage/v1/b \
	  -H "Content-Type: application/json" \
	  -d '{"name":"rag-fl-documents"}' > /dev/null && echo "  Bucket 'rag-fl-documents' ready." || echo "  Bucket already exists or fake-gcs not ready yet."
	@echo ""
	@echo "Run 'make ps' to see container health."
	@echo "Run 'make test-infra' to verify all checks pass."

## Stop all containers (keeps volumes)
down:
	docker compose down

## Follow logs for all containers (Ctrl+C to stop)
logs:
	docker compose logs -f

## Follow logs for a single service: make logs-s SERVICE=mongo
logs-s:
	docker compose logs -f $(SERVICE)

## Destroy everything: stop containers + wipe all volumes (DESTRUCTIVE)
reset:
	@echo "WARNING: This will DELETE all MongoDB data, Redis data, and GCS data."
	@echo "Press Ctrl+C within 5 seconds to cancel..."
	@sleep 5
	docker compose down -v --remove-orphans

## Show container status and health
ps:
	docker compose ps

# ── MongoDB shell ─────────────────────────────────────────────────────────────

## Open interactive mongosh against the ragfl database
mongo-shell:
	docker compose exec mongo mongosh ragfl

## Re-run collection + index creation (idempotent, safe to repeat)
mongo-init:
	docker compose run --rm mongo-init

# ── Redis shell ───────────────────────────────────────────────────────────────

## Open interactive redis-cli
redis-shell:
	docker compose exec redis redis-cli

# ── GCS (fake-gcs) ───────────────────────────────────────────────────────────

## Create the GCS bucket on fake-gcs-server (idempotent)
init-gcs:
	@echo "Creating bucket 'rag-fl-documents' on fake-gcs..."
	curl -s -X POST http://localhost:4443/storage/v1/b \
	  -H "Content-Type: application/json" \
	  -d '{"name":"rag-fl-documents"}' | cat
	@echo ""

## List all GCS buckets
list-gcs:
	curl -s http://localhost:4443/storage/v1/b | cat

# ── Infrastructure tests ──────────────────────────────────────────────────────

## Verify Phase 1 infra: MongoDB RS + collections, Redis, fake-gcs
test-infra:
	@echo "=== Phase 1 Infrastructure Checks ==="
	@echo ""
	@echo "--- MongoDB: replica set status ---"
	docker compose exec mongo mongosh --quiet --eval "rs.status().myState" ragfl
	@echo "(expected: 1 = PRIMARY)"
	@echo ""
	@echo "--- MongoDB: collections ---"
	docker compose exec mongo mongosh --quiet --eval \
	  "db.getCollectionNames().sort().join(', ')" ragfl
	@echo "(expected: citation_cache, doc_embeddings, documents, file_ledger, page_profiles)"
	@echo ""
	@echo "--- Redis: ping ---"
	docker compose exec redis redis-cli ping
	@echo "(expected: PONG)"
	@echo ""
	@echo "--- fake-gcs: list buckets ---"
	curl -sf http://localhost:4443/storage/v1/b | python3 -c \
	  "import sys,json; b=json.load(sys.stdin); print([i['name'] for i in b.get('items',[])])" 2>/dev/null || \
	  echo "(no buckets yet — run 'make init-gcs')"
	@echo ""
	@echo "--- Gotenberg/LibreOffice: health ---"
	curl -sf http://localhost:3000/health | cat || echo "not healthy"
	@echo ""
	@echo "=== All checks complete ==="

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "rag-fl Makefile commands:"
	@echo "  make up          — Start all infra containers"
	@echo "  make down        — Stop containers (keep data)"
	@echo "  make logs        — Follow all container logs"
	@echo "  make reset       — DESTROY all containers and volumes"
	@echo "  make ps          — Show container health status"
	@echo "  make mongo-shell — Interactive mongosh (ragfl db)"
	@echo "  make mongo-init  — Re-run collection/index creation"
	@echo "  make redis-shell — Interactive redis-cli"
	@echo "  make init-gcs    — Create GCS bucket on fake-gcs"
	@echo "  make test-infra  — Verify Phase 1 infra is healthy"
	@echo ""
