// ─────────────────────────────────────────────────────────────────────────────
// infra/mongo-init/collections.js
// Creates all 5 collections + indexes.
// Run against the ragfl database after replica set is PRIMARY.
// Safe to re-run — createCollection and createIndex are idempotent.
// ─────────────────────────────────────────────────────────────────────────────

// ── 1. documents ─────────────────────────────────────────────────────────────
db.createCollection("documents");
db.documents.createIndex({ "doc_id": 1 }, { unique: true, name: "doc_id_unique" });
db.documents.createIndex({ "status": 1 }, { name: "status" });
db.documents.createIndex({ "original_format": 1 }, { name: "original_format" });
db.documents.createIndex({ "created_at": -1 }, { name: "created_at_desc" });
print("✓ documents");

// ── 2. page_profiles ─────────────────────────────────────────────────────────
db.createCollection("page_profiles");
db.page_profiles.createIndex(
  { "doc_id": 1, "page_number": 1 },
  { unique: true, name: "doc_page_unique" }
);
db.page_profiles.createIndex({ "page_type": 1 }, { name: "page_type" });
db.page_profiles.createIndex({ "doc_id": 1 }, { name: "doc_id" });
print("✓ page_profiles");

// ── 3. doc_embeddings ────────────────────────────────────────────────────────
// Vector index (768-dim cosine) is Atlas-only.
// Local dev: cosine similarity computed in Python (shared/utils/vector_search.py).
// When Atlas is used, create a Search Index named "embedding_index" on "embedding"
// field with numDimensions=768, similarity=cosine via Atlas UI or API.
db.createCollection("doc_embeddings");
db.doc_embeddings.createIndex({ "chunk_id": 1 }, { unique: true, name: "chunk_id_unique" });
db.doc_embeddings.createIndex({ "doc_id": 1 }, { name: "doc_id" });
db.doc_embeddings.createIndex({ "doc_id": 1, "page_number": 1 }, { name: "doc_page" });
db.doc_embeddings.createIndex({ "chunk_type": 1 }, { name: "chunk_type" });
db.doc_embeddings.createIndex({ "embedding_model": 1 }, { name: "embedding_model" });
print("✓ doc_embeddings  (Atlas $vectorSearch index: create manually when migrating)");

// ── 4. file_ledger ───────────────────────────────────────────────────────────
db.createCollection("file_ledger");
db.file_ledger.createIndex({ "doc_id": 1 }, { unique: true, name: "doc_id_unique" });
db.file_ledger.createIndex({ "status": 1 }, { name: "status" });
db.file_ledger.createIndex({ "batch_id": 1 }, { name: "batch_id" });
db.file_ledger.createIndex({ "updated_at": -1 }, { name: "updated_at_desc" });
print("✓ file_ledger");

// ── 5. citation_cache — TTL collection (expires_at field, 1-hour TTL) ────────
db.createCollection("citation_cache");
db.citation_cache.createIndex({ "cache_key": 1 }, { unique: true, name: "cache_key_unique" });
// TTL index: MongoDB auto-deletes documents when expires_at < now
db.citation_cache.createIndex(
  { "expires_at": 1 },
  { expireAfterSeconds: 0, name: "expires_at_ttl" }
);
print("✓ citation_cache  (TTL on expires_at, expireAfterSeconds=0)");

print("");
print("All 5 collections created. Listing:");
db.getCollectionNames().forEach(function(c) { print("  - " + c); });
