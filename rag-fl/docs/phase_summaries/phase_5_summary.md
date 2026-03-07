# Phase 5 Summary

---

## Phase 5 — Citation Engine & Provenance API
**Completed:** 2026-03-07
**Status:** ✅ Complete
**Goal:** Build a Citation Engine that converts raw chunk_ids into human-readable citation labels with deep links, merges adjacent pages within the same document, caches results in MongoDB for 1 hour, and exposes a full provenance API for UI hover tooltips and audit trails.

---

## 1. Files Created

### services/rag-fl/ (new file)

| File | Description |
|---|---|
| `services/rag-fl/citation.py` | Full Citation Engine module. `APIRouter` with 4 endpoints. Implements `build_label()`, `build_deep_link()`, `_merge_adjacent()`, `_gemini_snippet()`, `_table_number()`, `_extract_table_cols()`, `_doc_display_name()`. Cache read/write via MongoDB `citation_cache{}` with SHA-256 keying. `_ensure_ttl_index()` silently handles IndexOptionsConflict (code 85). |

### Modified files

| File | Change |
|---|---|
| `services/rag-fl/main.py` | Added `from citation import router as citation_router` and `app.include_router(citation_router)`. No other changes — all endpoint logic lives in `citation.py`. |

---

## 2. New API Endpoints (services/rag-fl/citation.py)

| Endpoint | Purpose | Implementation notes |
|---|---|---|
| `POST /citations/generate` | Build citation labels for a list of `chunk_ids`. Merges adjacent pages (±1) within the same doc into one citation. Returns `label`, `page_number`, `page_number_end`, `doc_id`, `filename`, `chunk_type`, `deep_link`, `chunk_ids`. | Checks MongoDB cache first (SHA-256 key on sorted chunk_ids). On miss: fetches chunks + docs, groups by `(doc_id, page_number)`, sorts, merges adjacent, builds labels, writes cache. Returns `cached: true/false`. |
| `GET /citations/preview/{doc_id}/{page}` | Tooltip snippet for a single page: citation label + first 200 chars of the primary chunk. | Fetches lowest `chunk_index` chunk on the page. Returns `label`, `snippet`, `chunk_type`, `has_image`, `deep_link`. Projection explicitly includes `page_number` to avoid `get("page_number", 1)` defaulting. |
| `GET /provenance/document/{doc_id}` | Full per-page provenance breakdown for a document. Every page profile (including skip pages with 0 chunks) returned with per-chunk labels, snippets (120 chars), and deep links. | Iterates `page_profiles` sorted by `page_number`, then fetches chunks per page. Projection explicitly includes `page_number`. |
| `GET /provenance/chunk/{chunk_id}` | Full provenance trail for one chunk: citation, chunk text, all metadata, parent document fields, and the `page_profile` for the page it came from. | Uses `{"_id":0, "embedding":0}` exclusion projection — all other chunk fields (including `page_number`) naturally included. Pops `chunk_text` out of `chunk_metadata` into a top-level field. |

---

## 3. Citation Label Format

| Source type | Label pattern | Example |
|---|---|---|
| PDF text (with section title) | `{doc_name}, Page N, Section {section_title}` | `Churn EDA Report, Page 2, Section Executive Summary` |
| PDF text (no section title) | `{doc_name}, Page N` | `Churn EDA Report, Page 3` |
| PDF table | `{doc_name}, Page N, Table {n}: {col2} by {col1}` | `Churn EDA Report, Page 7, Table 7: Churn by customerID` |
| PDF multimodal | `{doc_name}, Page N, Figure: {first 10 Gemini words}` | `ChurnCustomer Jan2025, Page 1, Figure: Pearson correlation heatmap showing relationships between numerical` |
| Excel | `{filename}, Sheet: {sheet_name}, Rows {start}–{end}` | `CustomerChurn_Jan2025.xlsx, Sheet: Sheet1, Rows 1–28` |
| YAML | `{filename}, Key: {key_path}` | `config.yaml, Key: model.embedding.dimensionality` |

**`doc_name` stripping rules:**
- Excel/YAML: keep full filename (extension is semantically meaningful)
- PDF/other: strip extension, replace `_` with spaces

**Gemini snippet (`_gemini_snippet`):**
- Skips opener lines matching `^(here'?s?\s+(a\s+)?comprehensive|here\s+is\s+a|overall\s+(content|structure))`
- Strips markdown bold (`**`), italic (`*`), headers (`#`), bullets (`*`, `-`)
- Returns first 10 clean words

**Table numbering (`_table_number`):**
- 1-based, document-global (counts all `chunk_type=table` chunks preceding this chunk by `page_number` then `chunk_index`)

---

## 4. Adjacent Page Merging

`_merge_adjacent(groups)` runs a single-pass merge over groups sorted by `(doc_id, page_number)`. Two groups merge when:
- Same `doc_id`
- `g["page_number"] - last["page_end"] <= 1`

Merged group: `page_end` updated, `chunks` lists concatenated. The representative chunk (used for label + deep link) is always `group["chunks"][0]` (lowest page/chunk_index).

Result: a search returning chunks from pages 6 and 7 of the same document produces one citation, not two.

---

## 5. Citation Cache

| Property | Value |
|---|---|
| Collection | `citation_cache` |
| Cache key | SHA-256 of sorted, comma-joined `chunk_ids` |
| TTL | 1 hour (`expires_at = utcnow() + timedelta(hours=1)`) |
| Expiry enforcement | MongoDB TTL index on `expires_at` (`expireAfterSeconds=0`) |
| Write strategy | `replace_one(..., upsert=True)` — same chunk_ids always overwrite |
| Cache check | `find_one({"cache_key": key, "expires_at": {"$gt": utcnow()}})` |
| TTL index creation | `_ensure_ttl_index()` called on every `/citations/generate` request. Silently ignores `OperationFailure` with code 85 (IndexOptionsConflict) — index already exists under name `expires_at_ttl` from mongo-init. |

---

## 6. Deep Links

| Chunk type | Deep link |
|---|---|
| `multimodal` (has `gcs_image_path`) | `http://localhost:8004/image/{doc_id}/{page_number}` — direct PNG via image proxy |
| `text` / `table` / other | `http://localhost:3001/?doc_id={doc_id}&page={page_number}` — UI page anchor |

Base URLs configurable via environment variables:
- `CITATION_RAG_FL_BASE` (default: `http://localhost:8004`)
- `CITATION_UI_BASE` (default: `http://localhost:3001`)

---

## 7. How to Verify

### Generate citations

```bash
# Replace with real chunk_ids from your MongoDB doc_embeddings collection
CHUNK_IDS=$(mongosh --quiet ragfl \
  --eval 'JSON.stringify(db.doc_embeddings.find({},{chunk_id:1,_id:0}).limit(3).toArray().map(x=>x.chunk_id))')

curl -s -X POST http://localhost:8004/citations/generate \
  -H "Content-Type: application/json" \
  -d "{\"chunk_ids\": $CHUNK_IDS}" | python -m json.tool

# Expected:
# {
#   "citations": [{"label": "...", "page_number": N, "doc_id": "...", "chunk_type": "...", "deep_link": "...", ...}],
#   "count": 1,
#   "cached": false
# }

# Call again — should hit cache
curl -s -X POST http://localhost:8004/citations/generate \
  -H "Content-Type: application/json" \
  -d "{\"chunk_ids\": $CHUNK_IDS}" | python -m json.tool
# Expected: "cached": true
```

### Citation preview (tooltip)

```bash
# Replace doc_id and page with real values
curl -s http://localhost:8004/citations/preview/fb2c1e3e-a364-4470-9a5f-ea8f01aa8cd6/7 | python -m json.tool
# Expected:
# {
#   "doc_id": "fb2c1e3e-...",
#   "page": 7,
#   "label": "Churn EDA Report, Page 7, Table 7: Churn by customerID",
#   "snippet": "| customerID | Churn | ...",
#   "chunk_type": "table",
#   "has_image": false,
#   "deep_link": "http://localhost:3001/?doc_id=fb2c1e3e-...&page=7"
# }
```

### Provenance — full document

```bash
curl -s http://localhost:8004/provenance/document/fb2c1e3e-a364-4470-9a5f-ea8f01aa8cd6 | python -m json.tool
# Expected: doc metadata + pages[] array with per-page chunk_count and chunk labels
# Skip pages (chunk_count: 0) included for completeness
```

### Provenance — single chunk

```bash
CHUNK_ID=$(mongosh --quiet ragfl \
  --eval 'db.doc_embeddings.findOne({chunk_type:"multimodal"},{chunk_id:1,_id:0}).chunk_id')

curl -s "http://localhost:8004/provenance/chunk/$CHUNK_ID" | python -m json.tool
# Expected:
# {
#   "chunk_id": "...",
#   "citation": {"label": "ChurnCustomer Jan2025, Page 1, Figure: ...", "deep_link": "http://localhost:8004/image/...", ...},
#   "chunk_text": "Here's a comprehensive description...",
#   "chunk_metadata": {...},
#   "page_profile": {...},
#   "document": {...}
# }
```

### Cache hit in logs

```bash
docker compose logs rag-fl --tail=20 | grep citation
# Expected on first call:  citations: built N citation(s) for M chunk_id(s)
# Expected on second call: citations: cache hit for M chunk_ids
```

---

## 8. Actual Test Results

| Test | Result |
|---|---|
| `POST /citations/generate` (3 chunk_ids, first call) | `cached: false`, 1–3 citations returned with correct labels |
| `POST /citations/generate` (same chunk_ids, second call) | `cached: true`, identical response |
| Excel label | `CustomerChurn_Jan2025.xlsx, Sheet: Sheet1, Rows 1–28` (28 data rows, full sheet) |
| PDF multimodal label | `ChurnCustomer Jan2025, Page 1, Figure: {10 Gemini words}` — opener line skipped |
| PDF table label | `Churn EDA Report, Page 7, Table 7: Churn by customerID` (table 7, not 4 — 6 preceding table chunks in doc) |
| `GET /citations/preview/{doc_id}/7` | Correct label + 200-char snippet, `page_number` field present |
| `GET /provenance/document/{doc_id}` | All pages listed, skip pages included with `chunk_count: 0` |
| `GET /provenance/chunk/{chunk_id}` | Full provenance trail: citation, chunk_text, chunk_metadata, page_profile, document |
| TTL index conflict | Silently handled (code 85, index `expires_at_ttl` pre-exists from mongo-init) |

---

## 9. Deviations from Spec

| Decision | Spec says | What was implemented | Reason |
|---|---|---|---|
| TTL index creation | "TTL index on citation_cache.expires_at" | `_ensure_ttl_index()` catches `OperationFailure` code 85 silently | `mongo-init` already created the TTL index under name `expires_at_ttl` at first startup. Re-creating it with `create_index` raises IndexOptionsConflict. Safe to ignore — the index is already present and functional. |
| Table number | Sequential within section | Sequential within document (document-global) | Simpler query. Section boundaries are not stored in chunk metadata, making section-local counting unreliable. Document-global is consistent and predictable. |
| Signed GCS URLs | ARCHITECTURE.md §Citation mentions "signed GCS URL (1hr TTL) → serves PNG" | Image proxy URL (`/image/{doc_id}/{page}`) | fake-gcs-server does not support signed URL generation. The image proxy already serves PNGs with correct content-type and avoids CORS. Equivalent UX for a local POC. |
| `_merge_adjacent` sort scope | Not specified | Groups sorted globally by `(doc_id, page_number)` before merge | Required for correct merge behaviour when multiple documents are present. Single-pass merge only works if input is sorted. |
| `page_number` in projection | Implied | Explicitly added to all chunk projections in `citation_preview` and `provenance_document` | Initial omission caused all labels to read "Page 1" (default from `chunk.get("page_number", 1)`). Fixed before any real-use validation. |
| Phase 5 summary doc | Prompt says "Generate docs/phase_summaries/phase_5_summary.md" | This file | — |

---

## 10. Known Limitations / TODOs

- [ ] **No UI integration for provenance endpoints:** The UI (Phase 4) displays citation labels from search results but does not call `/citations/generate` dynamically or render hover tooltips from `/citations/preview`. Phase 6 can wire up the search results panel to call `POST /citations/generate` with the returned chunk_ids.
- [ ] **Document-global table numbering:** Table 7 in "Churn EDA Report" is globally the 7th table in the document, not the 7th in its section. If section-local numbering is needed, `section_title` would need to be added to the count query.
- [ ] **No signed GCS URLs:** Multimodal deep links point to the `/image` proxy rather than GCS-signed URLs. Phase 7 (Cloud Run) should switch to real GCS signed URLs with 1-hour TTL.
- [ ] **Adjacent merge is single-document-scoped but list is global:** If a request includes chunks from interleaved docs (doc_A p1, doc_B p1, doc_A p2), the sort-then-merge approach correctly separates them by `doc_id`. No known issue, but not stress-tested with interleaved inputs.
- [ ] **Cache is per exact chunk_id set:** Two requests with overlapping but not identical chunk_ids produce separate cache entries. No partial-cache optimisation.
- [ ] **`_ensure_ttl_index()` called on every `/citations/generate` request:** Acceptable for a POC. For production, call once at app startup via a `lifespan` event handler.

---

## 11. Prerequisites for Phase 6

Before starting Phase 6:

- [x] `POST /citations/generate` → correct labels for all chunk types (text, table, multimodal, Excel) ✅
- [x] `GET /citations/preview/{doc_id}/{page}` → correct label + snippet, `page_number` not defaulting to 1 ✅
- [x] `GET /provenance/document/{doc_id}` → all pages with per-chunk labels ✅
- [x] `GET /provenance/chunk/{chunk_id}` → full provenance trail ✅
- [x] Cache hit (`cached: true`) on second identical request ✅
- [x] IndexOptionsConflict handled silently ✅
- [x] Adjacent page merging: pages 6+7 from same doc → 1 citation ✅
- [x] Multimodal deep link → `/image` proxy URL ✅
- [x] Text/table deep link → UI URL with `?doc_id=&page=` ✅
- [x] `phase_5_summary.md` committed to `docs/phase_summaries/` ✅

**Phase 6 scope:** See `PHASES.md` for the next phase definition.
