# Phase 4 Summary

---

## Phase 4 — Next.js Observability UI
**Completed:** 2026-03-07
**Status:** ✅ Complete
**Goal:** Harsh's explicit request — "pick a file and explain what exactly is held there"

---

## 1. Files Created

### services/ui/ (new service)

| File | Description |
|---|---|
| `services/ui/Dockerfile` | `node:20-alpine`, runs `npm run dev` (next dev -p 3001). Dev mode reads NEXT_PUBLIC_* from process.env at startup — works with docker-compose environment block. |
| `services/ui/package.json` | Next.js 14.2.30, React 18, Tailwind CSS 3.3, TypeScript 5. Dev script: `next dev -p 3001`. |
| `services/ui/next.config.js` | Passes `NEXT_PUBLIC_RAG_FL_API`, `NEXT_PUBLIC_INGESTION_API`, `NEXT_PUBLIC_FORCE_MIXED_MODE` into the `env` block with localhost defaults. |
| `services/ui/tailwind.config.js` | Content paths scoped to `app/**` and `components/**`. |
| `services/ui/postcss.config.js` | `tailwindcss` + `autoprefixer` plugins. |
| `services/ui/tsconfig.json` | Next.js App Router TypeScript config. `moduleResolution: bundler`, `strict: true`. |
| `services/ui/app/layout.tsx` | Root layout. Sets `<title>RAG-FL Observability</title>`. `bg-slate-900 text-slate-100` base classes. |
| `services/ui/app/globals.css` | `@tailwind base/components/utilities` — no custom CSS beyond Tailwind. |
| `services/ui/app/page.tsx` | Full three-panel observability UI (see §4 for panel breakdown). Single client component (`"use client"`), all state in one file. 400 lines. |

### Modified files

| File | Change |
|---|---|
| `services/rag-fl/main.py` | Added CORS middleware (allows `localhost:3001`), `GET /image/{doc_id}/{page_number}`, `POST /search/within/{doc_id}`, `GET /config`. Version bumped to 4.0.0. |
| `docker-compose.yml` | Added `ui` service: context `./services/ui`, port `3001:3001`, env block with `NEXT_PUBLIC_RAG_FL_API=http://localhost:8004`, `NEXT_PUBLIC_INGESTION_API=http://localhost:8001`, `NEXT_PUBLIC_FORCE_MIXED_MODE`. |
| `docs/phase_summaries/phase_3_summary.md` | Updated with Form XObject fix (§8 deviations), corrected comparison test results (all three now pass), updated chunk totals (130 → 131). |

---

## 2. New API Endpoints (services/rag-fl/main.py)

| Endpoint | Purpose | Implementation notes |
|---|---|---|
| `GET /image/{doc_id}/{page_number}` | GCS image proxy. Browser fetches PNG without hitting fake-gcs directly (avoids CORS). | Calls `shared/utils/gcs_client.download_bytes(f"{doc_id}.{page_number}")`, returns `Response(content=..., media_type="image/png")`. Returns 404 if blob not found. |
| `POST /search/within/{doc_id}` | Embed query with `RETRIEVAL_QUERY` task type, run cosine similarity against all chunks for this doc, return top-k. | Calls `_embed_query()` (gemini-embedding-001, RETRIEVAL_QUERY, 768-dim), then `vector_search(filter_query={"doc_id": doc_id})`. Returns score, page_number, chunk_type, chunk_text[:200], section_title. |
| `GET /config` | Runtime config for the UI top bar. | Returns `force_mixed_mode` (from env), `environment`, `dry_run_threshold`. |
| CORS middleware | Allows `http://localhost:3001` and `http://127.0.0.1:3001` to call all rag-fl endpoints from the browser. | `CORSMiddleware`, `allow_methods=["*"]`, `allow_headers=["*"]`. |

---

## 3. UI Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  RAG-FL Observability  /  [selected doc name]     FORCE_MIXED_MODE false │
├───────────────────┬──────────────────────────────┬───────────────────┤
│  LEFT (288px)     │  CENTER (flex-1)              │  RIGHT (320px)    │
│                   │                               │                   │
│  [+ Upload File]  │  Page Explorer — N pages      │  Search           │
│                   │                               │  [textarea]       │
│  filename.pdf     │  pg 1  [table]   2 chunks ▼   │  [Search button]  │
│  EMBEDDED         │    ▼ expanded:                │                   │
│  PDF  15pg  21ch  │    [table] 768-dim ✓          │  84%  pg 7        │
│                   │    | Col | Col | Col |        │  [table]          │
│  Churn_EDA.pdf    │    |-----|-----|-----|        │  "| Churn | Int…" │
│  EMBEDDED         │    | val | val | val |        │                   │
│  PDF  9pg  12ch   │                               │  Citation label   │
│  ...              │  pg 2  [table]   2 chunks ▼   │                   │
│                   │  pg 3  [skip]    0 chunks ▼   │                   │
│  11 documents     │  pg 8  [multimodal] 1 chunk ▼ │                   │
│                   │    ▼ expanded:                │                   │
│                   │    [img] 768-dim ✓            │                   │
│                   │    Gemini: "Pearson heatmap…" │                   │
└───────────────────┴──────────────────────────────┴───────────────────┘
```

**Note:** Phase 4.1 removed the "[Process →]" button — auto-process now triggered by background task after upload. See `phase_4.1_workflow_improvements.md`.

**Badge colour scheme (as specified):**

| page_type | Badge class |
|---|---|
| text | `bg-blue-700 text-blue-100` |
| table | `bg-green-700 text-green-100` |
| multimodal | `bg-purple-700 text-purple-100` |
| mixed | `bg-orange-600 text-orange-100` |
| skip | `bg-slate-600 text-slate-400` |
| structured_text | `bg-cyan-700 text-cyan-100` |

---

## 4. How to Verify

### Containers

```bash
docker compose ps
# All 8 containers should be Up:
# ragfl-mongo (healthy), ragfl-redis (healthy), ragfl-fake-gcs (running),
# ragfl-ingestion (healthy), ragfl-pipeline (healthy),
# ragfl-ui (running), ragfl-libreoffice (running), ragfl-mongo-express (running)
```

### API endpoints

```bash
# Config endpoint (top bar FORCE_MIXED_MODE)
curl http://localhost:8004/config
# Expected: {"force_mixed_mode":"false","environment":"development","dry_run_threshold":10}

# Image proxy — fetch the ChurnCustomer screenshot page PNG
curl -o /dev/null -w "%{http_code} %{content_type} %{size_download} bytes" \
  http://localhost:8004/image/fb2c1e3e-a364-4470-9a5f-ea8f01aa8cd6/1
# Expected: 200 image/png 135971 bytes

# Search within document
curl -X POST http://localhost:8004/search/within/fb2c1e3e-a364-4470-9a5f-ea8f01aa8cd6 \
  -H "Content-Type: application/json" \
  -d '{"query": "customer churn table", "top_k": 3}'
# Expected: {"results": [...], "count": 1, "query": "customer churn table"}
```

### UI browser checks

| URL | What to verify |
|---|---|
| `http://localhost:3001` | Dark three-panel layout loads. Top bar shows "RAG-FL Observability" + `FORCE_MIXED_MODE false` in green. |
| Left panel | 11 documents listed with filename, format badge (PDF/XLSX), page count, chunk count, EMBEDDED status badge (green). |
| Click `Churn_EDA_Report.pdf` | Center panel shows 9 pages. Badges: table (green), skip (grey), multimodal (purple), mixed (orange). |
| Click page 8 (multimodal) | PNG image renders below the row (loaded via `GET /image/{doc_id}/8`). Below image: Gemini description of Pearson correlation heatmap. `768-dim ✓` in green. |
| Click page 1 (table) | Markdown table renders as HTML `<table>` with green header row. `768-dim ✓` in green. |
| Click page 1 (text) | Raw chunk text in monospace pre block. |
| Search: "churn rate fiber optic" | Right panel returns results with score bar (%), page badge, chunk type badge, 200-char snippet, citation label. Click a result → center panel scrolls to and expands that page. |
| Upload button | File picker opens. **Phase 4.1:** Auto-process in background, UI shows "Processing in background…" → "✅ filename embedded! N chunks" when complete. |

### Next.js startup log

```
docker compose logs ui --tail=10
# Expected:
#   ▲ Next.js 14.2.30
#   - Local: http://localhost:3001
#   ✓ Ready in ~2000ms
```

---

## 5. Comparison Test Results

Phase 4 does not run new data processing — this references Phase 3 comparison results.
All three comparison files now produce embedded chunks (Form XObject fix applied in Phase 3 post-run):

| File | Chunk type | Renders in UI | Notes |
|---|---|---|---|
| CustomerChurn_Jan2025.xlsx | table | Markdown → HTML table ✅ | 28 data rows, 10 columns |
| CustomerChurn_Jan2025 - Table.pdf | table | Markdown → HTML table ✅ | Identical row/col structure |
| ChurnCustomer_Jan2025.pdf | multimodal | PNG image + Gemini description ✅ | Fixed by XObject detection (Phase 3 post-run) |

---

## 6. API Usage

Phase 4 adds **one Gemini API call per search query** (embedding the user query with `RETRIEVAL_QUERY` task type). No Gemini Vision calls from the UI — those happen only when the pipeline processes a new document.

| Action | Gemini calls | Notes |
|---|---|---|
| File list load | 0 | Pure MongoDB read |
| Page explorer open | 0 | Pure MongoDB read |
| Multimodal image view | 0 | Served from fake-gcs via proxy, already stored |
| Search query | 1 embedding call | `gemini-embedding-001`, `RETRIEVAL_QUERY`, 768-dim |
| Upload + Process | Same as Phase 3 pipeline | Gemini Vision per multimodal/mixed page |

---

## 7. docker-compose.yml Change

```yaml
ui:
  build:
    context: ./services/ui
  container_name: ragfl-ui
  ports:
    - "3001:3001"
  networks:
    - ragfl
  depends_on:
    - ingestion
    - rag-fl
  environment:
    - NEXT_PUBLIC_RAG_FL_API=http://localhost:8004
    - NEXT_PUBLIC_INGESTION_API=http://localhost:8001
    - NEXT_PUBLIC_FORCE_MIXED_MODE=${FORCE_MIXED_MODE:-false}
  restart: unless-stopped
```

**Why `localhost` instead of Docker service names:** `NEXT_PUBLIC_*` env vars are bundled into browser-side JavaScript. The browser runs on the host machine, not inside Docker. `http://rag-fl:8004` would be unreachable from the browser. `http://localhost:8004` reaches the host-exposed port.

---

## 8. Deviations from CLAUDE_CODE_GUIDE.md Phase 4 Prompt

| Decision | Prompt says | What was implemented | Reason |
|---|---|---|---|
| Next.js version | Not specified | 14.2.30 (patched from 14.2.5) | `npm install` warned of critical security vulnerability in 14.2.5 (Next.js security advisory 2025-12-11). Upgraded to 14.2.30 — identical API, no code changes required. |
| `NEXT_PUBLIC_RAG_FL_API` default port | Prompt says 8002 | 8004 | rag-fl pipeline runs on port 8004 (set in Phase 3). The prompt had a typo. 8004 is the actual service port. |
| Server-side proxy vs direct browser fetch | Not specified | Direct browser fetch to localhost:8001/8004 | Simpler for a research tool. Avoids maintaining Next.js API routes that add no value. CORS middleware on rag-fl covers browser access. |
| `next dev` in Docker | Not specified | `next dev` instead of `next build` + `next start` | `NEXT_PUBLIC_*` env vars set in docker-compose `environment:` block are baked in at `next build` time — if the image is built before env vars are set, they'd be empty. `next dev` reads them from process.env at startup, making Docker env injection work correctly without ARG/build-time plumbing. Appropriate for a research tool. |
| Phase 4 summary doc | Prompt says "Generate docs/phase_summaries/phase_4_summary.md" | ✅ This file | — |

---

## 9. Known Limitations / TODOs

- [x] ~~**Upload processing status poll**~~ → **RESOLVED Phase 4.1:** Auto-process via background task implemented. UI polls every 3s and shows "✅ filename embedded! N chunks" when complete. See `phase_4.1_workflow_improvements.md`.
- [ ] **No healthcheck on ui container:** `docker compose ps` shows "running" but not "healthy". Add `healthcheck: test: ["CMD", "wget", "-qO-", "http://localhost:3001"]` if needed.
- [ ] **next dev security advisory:** Next.js 14.2.30 used but `next dev` is not recommended for production. Phase 7 (Cloud Run) should switch to `next build` + `next start` with build args for NEXT_PUBLIC_ vars.
- [ ] **Search requires EMBEDDED document:** Searching against a doc with no chunks returns 0 results silently. Should show "No embeddings yet — run Process first."
- [x] ~~**Duplicate docs in left panel**~~ → **RESOLVED Phase 4.1:** UI now filters `status === "EMBEDDED"` only. Files stuck at UPLOADED status are hidden. Content-hash deduplication from Phase 3 prevents duplicate uploads.
- [x] ~~**Multi-visual pages show same image**~~ → **RESOLVED Phase 3B (2026-03-08):** See §Phase 3B UI Fixes below.

---

---

# Phase 3B — UI Image Display Fix (applied 2026-03-08)
**Status:** ✅ Complete
**Scope:** Multi-visual page display — each multimodal chunk now shows its own distinct image crop.

---

## Problem

Pages with multiple visual elements (e.g. Titanic page 11 with 3 charts) stored separate
crops in GCS as `{doc_id}.{page}`, `{doc_id}.{page}.v1`, `{doc_id}.{page}.v2` — but the
UI always fetched `GET /image/{doc_id}/{page_number}` regardless of which chunk was
being displayed. Every chunk on a multi-visual page showed the same first crop.

## Changes

### `services/rag-fl/main.py`

Added `v: int = Query(0)` parameter to `GET /image/{doc_id}/{page_number}`:
```python
@app.get("/image/{doc_id}/{page_number}")
async def get_page_image(doc_id: str, page_number: int, v: int = Query(0)):
    gcs_path = f"{doc_id}.{page_number}" if v == 0 else f"{doc_id}.{page_number}.v{v}"
```
- `v=0` (default) → `{doc_id}.{page_number}` — backward compatible
- `v=1` → `{doc_id}.{page_number}.v1`
- `v=N` → `{doc_id}.{page_number}.vN`

### `services/ui/app/page.tsx`

Added `gcsImageUrl()` helper:
```typescript
function gcsImageUrl(gcsPath: string | undefined, docId: string, pageNum: number): string {
  const base = `${RAG_FL}/image/${docId}/${pageNum}`;
  if (!gcsPath) return base;
  const key = gcsPath.split("/").pop() ?? "";
  const vMatch = key.match(/\.v(\d+)$/);
  if (!vMatch) return base;
  return `${base}?v=${vMatch[1]}`;
}
```
Replaced hardcoded `src={RAG_FL/image/${doc_id}/${page_number}}` with
`src={gcsImageUrl(chunk.gcs_image_path, selectedDoc.doc_id, pg.page_number)}`.

The helper parses the `.v{n}` suffix directly from `chunk.gcs_image_path` stored in
`doc_embeddings`, so the correct crop is always served regardless of how many visuals
are on the page.

## Verification

```bash
# v=0 first visual (200)
curl -o /dev/null -w "%{http_code}" http://localhost:8004/image/{doc_id}/11
# v=1 second visual (200)
curl -o /dev/null -w "%{http_code}" http://localhost:8004/image/{doc_id}/11?v=1
# v=2 third visual (200)
curl -o /dev/null -w "%{http_code}" http://localhost:8004/image/{doc_id}/11?v=2
# v=99 nonexistent (404)
curl -o /dev/null -w "%{http_code}" http://localhost:8004/image/{doc_id}/11?v=99
```

---

## 10. Prerequisites for Phase 5 (Citation Engine & Provenance API)

Before starting Phase 5:

- [x] `docker compose ps` → all 8 containers Up ✅
- [x] `http://localhost:3001` → 200 OK, three-panel layout renders ✅
- [x] File list panel loads 11 documents with correct metadata ✅
- [x] Page explorer shows correct type badges per page ✅
- [x] Multimodal page expands → PNG image renders via `/image` proxy, Gemini description shown ✅
- [x] Table page expands → Markdown rendered as HTML `<table>` ✅
- [x] Search returns results with score bar, page badge, snippet, citation label ✅
- [x] Click search result → center panel scrolls to and expands that page ✅
- [x] `GET /image/{doc_id}/{page_number}` → 200 image/png ✅
- [x] `POST /search/within/{doc_id}` → results with score ✅
- [x] `GET /config` → force_mixed_mode, environment, dry_run_threshold ✅
- [x] CORS headers present on rag-fl responses (allows localhost:3001) ✅
- [x] Next.js 14.2.30 security patch applied ✅
- [x] phase_4_summary.md committed to docs/phase_summaries/ ✅

**Phase 5 scope:** Citation Engine & Provenance API.
Key endpoints to build:
- `POST /citations/generate {chunk_ids}` → `[{label, page_number, doc_id, deep_link, chunk_type}]`
- `GET /citations/preview/{doc_id}/{page}` → tooltip snippet
- `GET /provenance/document/{doc_id}` → full page breakdown
- `GET /provenance/chunk/{chunk_id}` → full provenance trail
Citation format reference: ARCHITECTURE.md §Citation Format by Source Type.
Citation cache: MongoDB `citation_cache{}` collection, TTL 1hr.
Deep links: PDF page anchor (`#page=N`) | multimodal = signed GCS URL (1hr TTL) → serves PNG.
