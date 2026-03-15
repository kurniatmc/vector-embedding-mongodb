## **1. INGESTION SERVICE** (Port 8001)
**Total: 5 endpoints**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/ingest` | Upload and ingest a document |
| GET | `/documents` | List all documents (paginated) |
| GET | `/documents/{doc_id}` | Get single document metadata |
| POST | `/webhooks/onedrive` | OneDrive webhook (stub) |

---

## **2. PIPELINE SERVICE** (Port 8004)
**Total: 8 endpoints**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/process` | Trigger pipeline processing for a doc |
| GET | `/documents` | List all documents with chunk counts |
| GET | `/document/{doc_id}/status` | Get document processing status |
| GET | `/document/{doc_id}/pages` | Get per-page profiles |
| GET | `/document/{doc_id}/chunks/{page_number}` | Get chunks for a specific page |
| GET | `/image/{doc_id}/{page_number}` | GCS image proxy (PNG) |
| GET | `/config` | Runtime configuration |

---

## **3. SEARCH SERVICE** (Port 8004 - via search.py router)
**Total: 3 endpoints**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/search` | Global semantic search with filters |
| POST | `/search/within/{doc_id}` | Document-scoped search |
| GET | `/document/{doc_id}/summary` | Document stats + page-type breakdown |

---

## **4. CITATION SERVICE** (Port 8004 - via citation.py router)
**Total: 4 endpoints**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/citations/generate` | Build citations from chunk_ids |
| GET | `/citations/preview/{doc_id}/{page}` | Tooltip preview for a page |
| GET | `/provenance/document/{doc_id}` | Full document provenance |
| GET | `/provenance/chunk/{chunk_id}` | Single chunk provenance trail |

---

## **SUMMARY**

| Service | Port | Endpoints |
|---------|------|-----------|
| Ingestion Service | 8001 | **5** |
| Pipeline Service | 8004 | **8** |
| Search Service | 8004 | **3** |
| Citation Service | 8004 | **4** |
| **TOTAL** | | **20** |

**Note:** All services run on 2 ports only (8001 and 8004). The Search and Citation "services" are actually routers included in the main RAG-FL Pipeline service (Port 8004), but logically they serve different purposes.