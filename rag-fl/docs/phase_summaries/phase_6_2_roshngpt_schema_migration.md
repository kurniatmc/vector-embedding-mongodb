# Phase 6.2 - RoshnGPT Schema Migration & Integration

**Date:** 15 March 2026
**Status:** Planning / Ready to Implement
**Meeting:** Sync with Harsh, Prasang, and Neha
**Objective:** Migrate RAG-FL schema to align with RoshnGPT production ecosystem

## Executive Summary

RAG-FL pipeline (Phases 1-6.1) has been developed with custom MongoDB schema and GCS structure. Production RoshnGPT system uses different schema architecture with 3 core collections and specific GCS path conventions. This phase migrates RAG-FL to production-ready RoshnGPT schema while maintaining backward compatibility.

**Key Quote from Harsh:**
> "Custom GPT, Document-dim, Document_embedding_private - these three are the pillars. Low level you can adapt anytime, but high level three components are needed."

## Current State (RAG-FL)

### MongoDB Collections
```
1. documents          → Custom schema with doc_id (UUID)
2. page_profiles      → Internal classification metadata
3. doc_embeddings     → Flat structure with chunk_id
4. file_ledger        → Processing audit trail
5. citation_cache     → Citation response cache
```

### GCS Structure (Mas Rahmad's Setup)
```
gs://vector_embedding_mongodb/
  └── file_name/
      └── doc_id.page
```

### DocumentRecord Schema (Current)
```python
class DocumentRecord(BaseModel):
    doc_id: str                      # UUID format
    filename: str
    original_format: str             # pdf, xlsx, etc
    gcs_path: str
    total_pages: int
    status: str                      # UPLOADED | EMBEDDED | FAILED
    content_hash: str
    report_series: Optional[str]     # For chronological metadata
    report_period: Optional[str]
    upload_timestamp: datetime
    uploaded_by: Optional[str]
    created_at: datetime
```

### ChunkRecord Schema (Current)
```python
class ChunkRecord(BaseModel):
    chunk_id: str                    # UUID format
    doc_id: str
    page_number: int
    chunk_type: str                  # text | table | multimodal
    chunk_text: str
    gcs_image_path: Optional[str]
    embedding: Optional[list[float]] # 768 dims
    embedding_model: Optional[str]
    processing_method: str           # existing | markitdown
```

## Target State (RoshnGPT)

### MongoDB Collections (3 Pillars)

#### 1. custom-gpt-dim (NEW - Universe Container)
**Purpose:** Manage access, authorization, and grouping for documents

```json
{
  "_id": "b0c55139-f559-5dd6-bdef-987be0d19268",
  "custom_gpt_id": "b0c55139-f559-5dd6-bdef-987be0d19268",
  "custom_gpt_name": "harsh-test-uploadfile",
  "user_id": "C8DVEvqJlze9ETKEIWpJ83KQHjo2",
  "user_name": "Harsh Ratde",
  "customgpt_created_at": "22/11/2025, 09:13:29",
  "customgpt_updated_at": "22/11/2025, 09:13:29",
  "gcloud_dir": "UGPT-C8DVEvqJlze9ETKEIWpJ83KQHjo2-harsh-test-uploadfile",
  "vectordb_collection_name": "UGPT-b0c55139-f559-5dd6-bdef-987be0d19268-VCT-COLLEC",
  "embedding": "Private Embedding Gemini Pro",
  "type_of_data": "Confidential",
  "is_active": true,
  "bypass_moderation": "no",
  "system_instruction": "",
  "llm_model_name": "undefined",
  "datasets": [],
  "sharedUsers": []
}
```

#### 2. document-dim (Extend from documents)
**Purpose:** File metadata with linkage to custom GPT

```json
{
  "_id": "doc_id_uuid",
  "referenceId": "b0c55139-f559-5dd6-bdef-987be0d19268",
  "custom_doc_id": "C8DVEvqJlze9ETKEIWpJ83KQHjo21765611519736",
  "file_name": "ROSHN___SEDRA_C8DVEvqJlze9ETKEIWpJ83KQHjo21765611519736.pdf",
  "file_name_original": "ROSHN___SEDRA.pdf",
  "file_format": "pdf",
  "file_mime_type": "application/pdf",
  "file_path": "roshngpt-doc-repo-dev2/roshn-gpt-document-repo/UGPT-.../file.pdf",
  "dir_path_gcp": "roshngpt-doc-repo-dev2/roshn-gpt-document-repo/UGPT-...",
  "source_dep": "UGPT-C8DVEvqJlze9ETKEIWpJ83KQHjo2-harsh-test-uploadfile",
  "uploaded_by": "Harsh Ratde",
  "user_id": "C8DVEvqJlze9ETKEIWpJ83KQHjo2",
  "uploadedAt": "13/12/2025, 10:38:39",
  "status": "Processed",
  "documentSensitivity": "Restricted [R]",
  "repoMasterCategory": "RoshnGPT",
  "extracted_image_gcp_paths": {
    "0": "roshngpt-doc-repo-dev2/roshn-gpt-document-images/.../page_1.png",
    "1": "roshngpt-doc-repo-dev2/roshn-gpt-document-images/.../page_2.png"
  },
  "isDocumentEmbeded": true,
  "isDocumentEmbeded_cloud": true,
  "num_chunks": 7,
  "fileLoaded": "multimodal_processed"
}
```

**Key Fields:**
- `referenceId`: MANDATORY link to custom_gpt_id
- `custom_doc_id`: Format `{user_id}{timestamp_milliseconds}` (replaces UUID)
- `extracted_image_gcp_paths`: Dict mapping page numbers to GCS paths
- `isDocumentEmbeded`: Boolean flag for embedding completion

#### 3. document_embedding_private (Restructure from doc_embeddings)
**Purpose:** Store embeddings with nested metadata structure

```json
{
  "_id": "chunk_id_uuid",
  "documents": "For file_name_original: Attribution_model_Phase1_Review_v2.pdf content…",
  "metadatas": {
    "source": "/tmp/data_store/Attribution_model_Phase1_Review_v2_C8DVEvqJlze9ETKEIWp…",
    "page": 0,
    "repoMasterCategory": "RoshnGPT",
    "folder_tag": null,
    "info_tag": "content",
    "sub-hierarchy": "UGPT-C8DVEvqJlze9ETKEIWpJ83KQHjo2-harsh-test-uploadfile",
    "primary_owner": "C8DVEvqJlze9ETKEIWpJ83KQHjo2",
    "file_path": "roshngpt-doc-repo-dev2/roshn-gpt-document-repo/...",
    "file_format": "pdf",
    "mongo_doc_ObjectId": "692154aa537e6403720779d5",
    "custom_doc_id": "C8DVEvqJlze9ETKEIWpJ83KQHjo21763792039323",
    "file_name_original": "Attribution_model_Phase1_Review_v2.pdf",
    "level": 1,
    "cluster": -1,
    "original_content": "## 1. OCR Text Extraction...",
    "image_gcp_path": "roshngpt-doc-repo-dev2/roshn-gpt-document-images/..."
  },
  "ids": ["UGPT-b0c55139-f559-5dd6-bdef-987be0d19268-VCT-COLLEC"],
  "document_name_id": "UGPT-b0c55139-f559-5dd6-bdef-987be0d19268-VCT-COLLEC",
  "raptor_processed": false,
  "custom_gpt_id": "b0c55139-f559-5dd6-bdef-987be0d19268",
  "image_gcp_path": "roshngpt-doc-repo-dev2/roshn-gpt-document-images/...",
  "embedding": [0.123, 0.456, ...]
}
```

**Key Changes:**
- Flat structure → Nested `metadatas` dict
- `chunk_text` → `documents` (top-level)
- All metadata wrapped inside `metadatas` object
- `document_name_id` from custom GPT's vectordb_collection_name

### GCS Structure (RoshnGPT)

```
gs://roshngpt-doc-repo-dev2/
  ├── roshn-gpt-document-repo/
  │   └── UGPT-{user_id}-{custom_gpt_name}/
  │       └── {file_name_normalized}_{custom_doc_id}.{ext}
  │
  └── roshn-gpt-document-images/
      └── {custom_doc_id}/
          ├── page_1.png
          ├── page_2.png
          └── page_N.png
```

**Path Examples:**
```
Document:
gs://roshngpt-doc-repo-dev2/roshn-gpt-document-repo/UGPT-C8DVEvqJlze9ETKEIWpJ83KQHjo2-harsh-test/ROSHN___SEDRA_C8DVEvqJlze9ETKEIWpJ83KQHjo21765611519736.pdf

Images:
gs://roshngpt-doc-repo-dev2/roshn-gpt-document-images/C8DVEvqJlze9ETKEIWpJ83KQHjo21765611519736/page_1.png
gs://roshngpt-doc-repo-dev2/roshn-gpt-document-images/C8DVEvqJlze9ETKEIWpJ83KQHjo21765611519736/page_2.png
```

## Gap Analysis

### Missing Collections
1. **custom-gpt-dim**: 100% new, no equivalent in RAG-FL

### Missing Fields in documents → document-dim

**CRITICAL (Mandatory):**
- `referenceId` - Link to custom_gpt_id (enables multi-tenancy)
- `custom_doc_id` - New ID format: {user_id}{timestamp_ms}
- `user_id` - Document owner identifier

**IMPORTANT (Required for RoshnGPT):**
- `file_name_original` - Original filename with spaces
- `file_name` - Normalized filename (underscores)
- `dir_path_gcp` - GCS directory path
- `file_path` - Full GCS file path
- `source_dep` - gcloud_dir from custom-gpt-dim
- `repoMasterCategory` - Always "RoshnGPT"
- `documentSensitivity` - "Restricted [R]"

**METADATA (Operational):**
- `extracted_image_gcp_paths` - Dict: {page_num: gcs_path}
- `fileLoaded` - "multimodal_processed"
- `num_chunks` - Total chunk count
- `isDocumentEmbeded` - Embedding completion flag
- `isDocumentEmbeded_cloud` - Cloud deployment flag

### Structure Changes

**doc_embeddings → document_embedding_private:**

| Current (Flat) | Target (Nested) | Change Type |
|----------------|-----------------|-------------|
| chunk_text | documents | Rename |
| page_number, file_path, etc | metadatas.{field} | Wrap in metadatas |
| doc_id | metadatas.mongo_doc_ObjectId | Move + rename |
| (none) | custom_gpt_id | Add top-level |
| (none) | document_name_id | Add top-level |
| (none) | ids[] | Add top-level |
| embedding[] | embedding[] | Keep as-is |

### GCS Path Changes

| Source | Current | Target |
|--------|---------|--------|
| Documents | gs://vector_embedding_mongodb/filename/doc_id.page | gs://roshngpt-doc-repo-dev2/roshn-gpt-document-repo/UGPT-{user_id}-{gpt_name}/{file}_{custom_doc_id}.ext |
| Images | gs://vector_embedding_mongodb/filename/doc_id.page | gs://roshngpt-doc-repo-dev2/roshn-gpt-document-images/{custom_doc_id}/page_{N}.png |

## Data Flow & Linkage

```
┌─────────────────────────┐
│   custom-gpt-dim        │
│                         │
│  custom_gpt_id (UUID)   │◄─────────┐
│  gcloud_dir             │          │
│  vectordb_collection... │          │
└─────────────────────────┘          │
                                     │
                              referenceId
                                     │
┌─────────────────────────┐          │
│   document-dim          │          │
│                         │──────────┘
│  referenceId            │
│  custom_doc_id          │◄─────────┐
│  user_id                │          │
│  file_path              │          │
│  extracted_image_...    │          │
└─────────────────────────┘          │
                                     │
                          metadatas.custom_doc_id
                          metadatas.mongo_doc_ObjectId
                                     │
┌─────────────────────────┐          │
│ document_embedding_...  │          │
│                         │──────────┘
│  custom_gpt_id          │
│  document_name_id       │
│  metadatas: {           │
│    custom_doc_id        │
│    mongo_doc_ObjectId   │
│    ...                  │
│  }                      │
│  embedding[]            │
└─────────────────────────┘
```

**Linkage Rules:**
1. Every document MUST have `referenceId = custom_gpt_id`
2. Every embedding MUST have `custom_gpt_id` at top level
3. Every embedding MUST have `metadatas.custom_doc_id` linking to document
4. `document_name_id` derived from custom GPT's `vectordb_collection_name`

## End-to-End Roadmap

### Phase 0: Connection & Environment Setup (2 hours)

**Goal:** Connect to MongoDB Atlas and GCS production

**Prerequisites from Mas Rahmad:**
- [ ] MongoDB Atlas connection string (mongodb+srv://...)
- [ ] Database name (likely: roshngpt or roshn-gpt)
- [ ] GCS service account key JSON
- [ ] Bucket name: vector_embedding_mongodb (confirm)
- [ ] User ID for testing
- [ ] Read/write permissions verified

**Deliverables:**
```bash
# .env additions
MONGODB_ATLAS_URI=mongodb+srv://username:password@cluster.mongodb.net/database
MONGODB_ATLAS_DB=roshngpt
GCS_BUCKET=vector_embedding_mongodb
GCS_SERVICE_ACCOUNT_KEY_PATH=/path/to/key.json
GCS_PROJECT_ID=your-project-id
```

**Test Script:**
```python
# scripts/test_connection.py
from pymongo import MongoClient
from google.cloud import storage
import os

# MongoDB Atlas
client = MongoClient(os.getenv("MONGODB_ATLAS_URI"))
db = client[os.getenv("MONGODB_ATLAS_DB")]
print(f"✓ MongoDB: {db.name}, collections: {db.list_collection_names()}")

# GCS
storage_client = storage.Client.from_service_account_json(
    os.getenv("GCS_SERVICE_ACCOUNT_KEY_PATH")
)
bucket = storage_client.bucket(os.getenv("GCS_BUCKET"))
print(f"✓ GCS: {bucket.name}")
```

### Phase 1: Create custom-gpt-dim Collection (3 hours)

**Goal:** Implement GPT universe container

**Files to Create:**

1. `shared/schemas/custom_gpt.py`
```python
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

class CustomGPTRecord(BaseModel):
    custom_gpt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    custom_gpt_name: str
    user_id: str
    user_name: str
    customgpt_created_at: str  # "DD/MM/YYYY, HH:MM:SS"
    customgpt_updated_at: str
    gcloud_dir: str  # "UGPT-{user_id}-{custom_gpt_name}"
    vectordb_collection_name: str  # "UGPT-{custom_gpt_id}-VCT-COLLEC"
    embedding: str = "Private Embedding Gemini Pro"
    type_of_data: str = "Confidential"
    is_active: bool = True

    def to_mongo(self) -> dict:
        d = self.model_dump()
        d["_id"] = d.pop("custom_gpt_id")
        return d
```

2. `services/rag-fl/custom_gpt_manager.py`
```python
from shared.schemas.custom_gpt import CustomGPTRecord
from shared.utils.mongo_client import get_db
from datetime import datetime
import uuid

def create_custom_gpt(gpt_name: str, user_id: str, user_name: str) -> str:
    custom_gpt_id = str(uuid.uuid4())
    timestamp = datetime.now().strftime("%d/%m/%Y, %H:%M:%S")
    gcloud_dir = f"UGPT-{user_id}-{gpt_name}"
    vectordb_collection = f"UGPT-{custom_gpt_id}-VCT-COLLEC"

    gpt_record = CustomGPTRecord(
        custom_gpt_id=custom_gpt_id,
        custom_gpt_name=gpt_name,
        user_id=user_id,
        user_name=user_name,
        customgpt_created_at=timestamp,
        customgpt_updated_at=timestamp,
        gcloud_dir=gcloud_dir,
        vectordb_collection_name=vectordb_collection
    )

    db = get_db()
    db["custom-gpt-dim"].insert_one(gpt_record.to_mongo())
    return custom_gpt_id
```

3. `scripts/create_custom_gpt.py`
```python
#!/usr/bin/env python3
import sys
sys.path.insert(0, ".")
from services.rag_fl.custom_gpt_manager import create_custom_gpt
import yaml, argparse

parser = argparse.ArgumentParser()
parser.add_argument("--config", required=True)
args = parser.parse_args()

with open(args.config) as f:
    config = yaml.safe_load(f)

custom_gpt_id = create_custom_gpt(
    gpt_name=config["custom_gpt_name"],
    user_id=config["user_id"],
    user_name=config["user_name"]
)
print(f"SUCCESS: custom_gpt_id = {custom_gpt_id}")
```

4. `config/custom_gpt_config.yaml`
```yaml
custom_gpt_name: "kurnia-rag-embedding"
user_id: "C8DVEvqJlze9ETKEIWpJ83KQHjo2"
user_name: "Kurnia A. Ra'if"
```

**MongoDB Index:**
```javascript
// infra/mongo-init/collections.js
db.createCollection("custom-gpt-dim");
db["custom-gpt-dim"].createIndex(
  { "custom_gpt_id": 1 },
  { unique: true, name: "custom_gpt_id_unique" }
);
db["custom-gpt-dim"].createIndex({ "user_id": 1 }, { name: "user_id" });
db["custom-gpt-dim"].createIndex({ "is_active": 1 }, { name: "is_active" });
```

**Testing:**
```bash
python scripts/create_custom_gpt.py --config config/custom_gpt_config.yaml
# Output: custom_gpt_id = b0c55139-f559-5dd6-bdef-987be0d19268
```

### Phase 2: Extend document-dim Schema (4 hours)

**Goal:** Add 13 missing RoshnGPT fields to DocumentRecord

**Schema Update:**
```python
# shared/schemas/document.py (add after existing fields)
class DocumentRecord(BaseModel):
    # Existing fields (keep all)
    doc_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    original_format: str
    gcs_path: str
    total_pages: int
    status: str = "UPLOADED"
    content_hash: str
    report_series: Optional[str] = None
    report_period: Optional[str] = None
    upload_timestamp: datetime = Field(default_factory=datetime.utcnow)
    uploaded_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # NEW RoshnGPT fields
    referenceId: Optional[str] = None  # CRITICAL: custom_gpt_id link
    custom_doc_id: Optional[str] = None  # {user_id}{timestamp_ms}
    file_name_original: Optional[str] = None
    file_name: Optional[str] = None
    dir_path_gcp: Optional[str] = None
    file_path: Optional[str] = None
    source_dep: Optional[str] = None  # gcloud_dir
    user_id: Optional[str] = None
    repoMasterCategory: str = "RoshnGPT"
    documentSensitivity: str = "Restricted [R]"
    extracted_image_gcp_paths: dict = Field(default_factory=dict)
    fileLoaded: Optional[str] = None
    num_chunks: int = 0
    isDocumentEmbeded: bool = False
    isDocumentEmbeded_cloud: bool = False
```

**Ingestion Update:**
```python
# services/ingestion/app/main.py
@app.post("/ingest")
async def ingest_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    custom_gpt_id: str = Form(...),  # NEW MANDATORY
    user_id: str = Form(...),
    user_name: str = Form(...),
    report_series: str = Form(None),
    report_period: str = Form(None),
):
    # Get custom GPT metadata
    from services.rag_fl.custom_gpt_manager import get_custom_gpt
    gpt = get_custom_gpt(custom_gpt_id)
    if not gpt:
        raise HTTPException(400, f"custom_gpt_id {custom_gpt_id} not found")

    # Generate custom_doc_id
    import time
    timestamp_ms = int(time.time() * 1000)
    custom_doc_id = f"{user_id}{timestamp_ms}"

    # Filenames
    file_name_original = result["filename"]
    file_name = file_name_original.replace(" ", "_")

    # GCS paths
    gcloud_dir = gpt["gcloud_dir"]
    bucket = os.getenv("GCS_BUCKET")
    dir_path_gcp = f"{bucket}/roshn-gpt-document-repo/{gcloud_dir}"
    file_path = f"{dir_path_gcp}/{file_name}_{custom_doc_id}.{original_format}"

    # Create DocumentRecord
    doc = DocumentRecord(
        doc_id=doc_id,
        filename=result["filename"],
        original_format=original_format,
        # ... existing fields ...

        # RoshnGPT fields
        referenceId=custom_gpt_id,
        custom_doc_id=custom_doc_id,
        file_name_original=file_name_original,
        file_name=file_name,
        dir_path_gcp=dir_path_gcp,
        file_path=file_path,
        source_dep=gcloud_dir,
        user_id=user_id,
        uploaded_by=user_name,
    )
    # ... rest of ingestion ...
```

**MongoDB Indexes:**
```javascript
db.documents.createIndex({ "referenceId": 1 }, { name: "referenceId" });
db.documents.createIndex({ "custom_doc_id": 1 }, { name: "custom_doc_id" });
db.documents.createIndex({ "user_id": 1 }, { name: "user_id" });
```

**Testing:**
```bash
curl -X POST http://localhost:8001/ingest \
  -F "file=@test.pdf" \
  -F "custom_gpt_id=b0c55139-f559-5dd6-bdef-987be0d19268" \
  -F "user_id=C8DVEvqJlze9ETKEIWpJ83KQHjo2" \
  -F "user_name=Kurnia"
```

### Phase 3: Update GCS Path Structure (3 hours)

**Goal:** Migrate from Mas Rahmad paths to RoshnGPT paths

**GCS Client Update:**
```python
# shared/utils/gcs_client.py

def get_roshngpt_document_path(
    user_id: str,
    custom_gpt_name: str,
    filename: str,
    custom_doc_id: str,
    file_format: str
) -> str:
    """RoshnGPT document path: UGPT-{user_id}-{gpt_name}/{file}_{custom_doc_id}.ext"""
    gcloud_dir = f"UGPT-{user_id}-{custom_gpt_name}"
    normalized = filename.replace(" ", "_")
    return f"roshn-gpt-document-repo/{gcloud_dir}/{normalized}_{custom_doc_id}.{file_format}"

def get_roshngpt_image_path(custom_doc_id: str, page_number: int) -> str:
    """RoshnGPT image path: {custom_doc_id}/page_{N}.png"""
    return f"roshn-gpt-document-images/{custom_doc_id}/page_{page_number}.png"
```

**Chunker Update:**
```python
# services/rag-fl/chunker.py (in render_and_upload_visual_region)

def render_and_upload_visual_region(...):
    # ... existing render logic ...

    # Get document metadata
    from shared.utils.mongo_client import get_documents_col
    doc_meta = get_documents_col().find_one({"doc_id": doc_id})
    custom_doc_id = doc_meta.get("custom_doc_id")

    if custom_doc_id:
        # RoshnGPT path
        from shared.utils.gcs_client import get_roshngpt_image_path
        gcs_path = get_roshngpt_image_path(custom_doc_id, page_number)
        if visual_index > 0:
            gcs_path = gcs_path.replace(".png", f".v{visual_index}.png")
    else:
        # Fallback to old format
        gcs_path = f"{doc_id}.{page_number}.v{visual_index}"

    # Upload and store in extracted_image_gcp_paths
    gcs_url = upload_to_gcs(img_bytes, gcs_path, "image/png")

    get_documents_col().update_one(
        {"doc_id": doc_id},
        {"$set": {f"extracted_image_gcp_paths.{page_number}": gcs_url}}
    )

    return gcs_url
```

**Testing:**
```bash
# Verify GCS structure
gsutil ls -r gs://vector_embedding_mongodb/roshn-gpt-document-repo/
gsutil ls -r gs://vector_embedding_mongodb/roshn-gpt-document-images/
```

### Phase 4: Restructure Embeddings Schema (5 hours)

**Goal:** Convert flat ChunkRecord to nested document_embedding_private

**New Schema:**
```python
# shared/schemas/embedding_private.py
from pydantic import BaseModel, Field
from typing import Dict, List, Any, Optional

class EmbeddingPrivateRecord(BaseModel):
    documents: str  # chunk_text content

    metadatas: Dict[str, Any] = Field(default_factory=dict)
    # {
    #   "source": str,
    #   "page": int,  # 0-indexed
    #   "repoMasterCategory": "RoshnGPT",
    #   "folder_tag": None,
    #   "info_tag": "content",
    #   "sub-hierarchy": str,  # gcloud_dir
    #   "primary_owner": str,  # user_id
    #   "file_path": str,
    #   "file_format": str,
    #   "mongo_doc_ObjectId": str,
    #   "custom_doc_id": str,
    #   "file_name_original": str,
    #   "level": 1,
    #   "cluster": -1,
    #   "original_content": str,
    #   "image_gcp_path": str
    # }

    ids: List[str] = Field(default_factory=list)
    document_name_id: str
    raptor_processed: bool = False
    custom_gpt_id: str
    image_gcp_path: Optional[str] = None
    embedding: List[float] = Field(default_factory=list)

    chunk_id: Optional[str] = None  # For mapping

    def to_mongo(self) -> dict:
        d = self.model_dump()
        if d.get("chunk_id"):
            d["_id"] = d.pop("chunk_id")
        return d
```

**Converter Function:**
```python
# services/rag-fl/embedding_converter.py
from shared.schemas.chunk import ChunkRecord
from shared.schemas.embedding_private import EmbeddingPrivateRecord

def convert_chunk_to_embedding_private(
    chunk: ChunkRecord,
    doc_meta: dict,
    gpt_meta: dict
) -> EmbeddingPrivateRecord:
    metadatas = {
        "source": doc_meta.get("gcs_path", ""),
        "page": chunk.page_number - 1,  # 0-indexed
        "repoMasterCategory": "RoshnGPT",
        "folder_tag": None,
        "info_tag": "content",
        "sub-hierarchy": gpt_meta.get("gcloud_dir", ""),
        "primary_owner": doc_meta.get("user_id", ""),
        "file_path": doc_meta.get("file_path", ""),
        "file_format": doc_meta.get("original_format", ""),
        "mongo_doc_ObjectId": str(doc_meta.get("_id", "")),
        "custom_doc_id": doc_meta.get("custom_doc_id", ""),
        "file_name_original": doc_meta.get("file_name_original", ""),
        "level": 1,
        "cluster": -1,
        "original_content": chunk.chunk_text,
        "image_gcp_path": chunk.gcs_image_path or ""
    }

    document_name_id = gpt_meta.get("vectordb_collection_name", "")

    return EmbeddingPrivateRecord(
        documents=chunk.chunk_text,
        metadatas=metadatas,
        ids=[document_name_id],
        document_name_id=document_name_id,
        custom_gpt_id=doc_meta.get("referenceId", ""),
        image_gcp_path=chunk.gcs_image_path,
        embedding=chunk.embedding or [],
        chunk_id=chunk.chunk_id
    )
```

**Embedder Update:**
```python
# services/rag-fl/embedder.py

def store_embeddings(chunks: list[ChunkRecord], doc_id: str):
    from embedding_converter import convert_chunk_to_embedding_private
    from shared.utils.mongo_client import get_db

    db = get_db()
    doc_meta = db.documents.find_one({"doc_id": doc_id})

    gpt_id = doc_meta.get("referenceId")
    if not gpt_id:
        # Old document - store in doc_embeddings only
        for chunk in chunks:
            db.doc_embeddings.insert_one(chunk.to_mongo())
        return

    gpt_meta = db["custom-gpt-dim"].find_one({"_id": gpt_id})

    # Store in BOTH collections (backward compatibility)
    for chunk in chunks:
        # 1. Old format
        db.doc_embeddings.insert_one(chunk.to_mongo())

        # 2. RoshnGPT format
        emb_private = convert_chunk_to_embedding_private(chunk, doc_meta, gpt_meta)
        db.document_embedding_private.insert_one(emb_private.to_mongo())

    # Update document flags
    db.documents.update_one(
        {"doc_id": doc_id},
        {"$set": {
            "num_chunks": len(chunks),
            "isDocumentEmbeded": True,
            "isDocumentEmbeded_cloud": True,
            "fileLoaded": "multimodal_processed"
        }}
    )
```

**MongoDB Index:**
```javascript
db.createCollection("document_embedding_private");
db.document_embedding_private.createIndex(
  { "chunk_id": 1 },
  { unique: true, name: "chunk_id_unique" }
);
db.document_embedding_private.createIndex(
  { "custom_gpt_id": 1 },
  { name: "custom_gpt_id" }
);
db.document_embedding_private.createIndex(
  { "document_name_id": 1 },
  { name: "document_name_id" }
);
```

**Testing:**
```bash
# Process document
python services/rag-fl/pipeline.py --file test.pdf --yes

# Verify both collections
mongosh --eval "db.doc_embeddings.countDocuments({})"
mongosh --eval "db.document_embedding_private.countDocuments({})"

# Check structure
mongosh --eval "db.document_embedding_private.findOne()" | jq
```

### Phase 5: Create Standalone Scripts (3 hours)

**Goal:** 3 independent scripts for GPT creation, upload, embedding

**Script 1:** `scripts/create_custom_gpt.py` (already created in Phase 1)

**Script 2:** `scripts/upload_document.py`
```python
#!/usr/bin/env python3
import sys
sys.path.insert(0, ".")
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--file", required=True, help="Path to file")
parser.add_argument("--custom-gpt-id", required=True)
parser.add_argument("--user-id", required=True)
parser.add_argument("--user-name", required=True)
parser.add_argument("--report-series", default=None)
parser.add_argument("--report-period", default=None)
args = parser.parse_args()

# Programmatic upload
import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder

file_path = Path(args.file)
if not file_path.exists():
    print(f"ERROR: File {args.file} not found")
    sys.exit(1)

with open(file_path, "rb") as f:
    fields = {
        "file": (file_path.name, f, "application/octet-stream"),
        "custom_gpt_id": args.custom_gpt_id,
        "user_id": args.user_id,
        "user_name": args.user_name,
    }
    if args.report_series:
        fields["report_series"] = args.report_series
    if args.report_period:
        fields["report_period"] = args.report_period

    multipart = MultipartEncoder(fields=fields)

    response = requests.post(
        "http://localhost:8001/ingest",
        data=multipart,
        headers={"Content-Type": multipart.content_type}
    )

if response.status_code == 200:
    result = response.json()
    print(f"\nSUCCESS:")
    print(f"  custom_doc_id: {result['custom_doc_id']}")
    print(f"  doc_id: {result['doc_id']}")
    print(f"  status: {result['status']}")
else:
    print(f"ERROR: {response.status_code} - {response.text}")
    sys.exit(1)
```

**Script 3:** `scripts/embed_document.py`
```python
#!/usr/bin/env python3
import sys
sys.path.insert(0, ".")
import argparse
from shared.utils.mongo_client import get_db
from services.rag_fl.pipeline import process_document

parser = argparse.ArgumentParser()
parser.add_argument("--custom-doc-id", required=True)
args = parser.parse_args()

# Get doc_id from custom_doc_id
db = get_db()
doc = db.documents.find_one({"custom_doc_id": args.custom_doc_id})

if not doc:
    print(f"ERROR: Document with custom_doc_id {args.custom_doc_id} not found")
    sys.exit(1)

doc_id = doc["doc_id"]
print(f"Processing document: {doc.get('file_name_original')}")
print(f"  doc_id: {doc_id}")

result = process_document(doc_id, classify_only=False)

print(f"\nSUCCESS:")
print(f"  Chunks created: {result['chunks_created']}")
print(f"  Gemini calls: {result.get('gemini_calls', 0)}")
print(f"  Status: EMBEDDED")
```

**End-to-End Test:**
```bash
# 1. Create GPT
python scripts/create_custom_gpt.py --config config/custom_gpt_config.yaml
# Output: custom_gpt_id = abc-123

# 2. Upload document
python scripts/upload_document.py \
  --file tests/sample-docs/Churn_EDA_Report.pdf \
  --custom-gpt-id abc-123 \
  --user-id C8DVEvqJlze9ETKEIWpJ83KQHjo2 \
  --user-name "Kurnia"
# Output: custom_doc_id = C8DVEvqJlze9ETKEIWpJ83KQHjo21710537600000

# 3. Embed document
python scripts/embed_document.py \
  --custom-doc-id C8DVEvqJlze9ETKEIWpJ83KQHjo21710537600000
# Output: 23 chunks embedded
```

### Phase 6: Testing & Validation (2 hours)

**Goal:** Verify end-to-end integration and data linkage

**Validation Script:**
```python
# scripts/validate_roshngpt_integration.py
import sys
sys.path.insert(0, ".")
from shared.utils.mongo_client import get_db

db = get_db()

print("="*60)
print("RoshnGPT Integration Validation")
print("="*60)

# 1. Check custom-gpt-dim
gpt_count = db["custom-gpt-dim"].count_documents({})
print(f"\n1. custom-gpt-dim: {gpt_count} GPTs")
if gpt_count == 0:
    print("   ❌ No GPTs found")
    print("   Action: Run scripts/create_custom_gpt.py")
else:
    gpt = db["custom-gpt-dim"].find_one()
    print(f"   ✓ Sample GPT: {gpt['custom_gpt_name']}")
    print(f"     custom_gpt_id: {gpt['custom_gpt_id']}")
    print(f"     gcloud_dir: {gpt['gcloud_dir']}")

# 2. Check document-dim
docs = list(db.documents.find({"referenceId": {"$exists": True}}).limit(5))
print(f"\n2. document-dim: {len(docs)} documents with referenceId")
if not docs:
    print("   ❌ No documents linked to GPT")
    print("   Action: Upload with custom_gpt_id parameter")
else:
    doc = docs[0]
    print(f"   ✓ Sample doc: {doc.get('file_name_original')}")
    print(f"     referenceId: {doc.get('referenceId')}")
    print(f"     custom_doc_id: {doc.get('custom_doc_id')}")
    print(f"     user_id: {doc.get('user_id')}")
    print(f"     num_chunks: {doc.get('num_chunks')}")
    print(f"     isDocumentEmbeded: {doc.get('isDocumentEmbeded')}")

# 3. Check document_embedding_private
emb_count = db.document_embedding_private.count_documents({})
print(f"\n3. document_embedding_private: {emb_count} embeddings")
if emb_count == 0:
    print("   ❌ No embeddings in RoshnGPT format")
    print("   Action: Run scripts/embed_document.py")
else:
    emb = db.document_embedding_private.find_one()
    print(f"   ✓ Structure validation:")
    print(f"     - documents: {type(emb.get('documents')).__name__}")
    print(f"     - metadatas: {type(emb.get('metadatas')).__name__}")
    print(f"     - custom_gpt_id: {emb.get('custom_gpt_id')}")
    print(f"     - document_name_id: {emb.get('document_name_id')}")

    # Validate metadatas structure
    meta = emb.get('metadatas', {})
    required_keys = [
        "custom_doc_id", "mongo_doc_ObjectId", "file_path",
        "primary_owner", "sub-hierarchy", "page"
    ]
    missing = [k for k in required_keys if k not in meta]
    if missing:
        print(f"   ⚠ Missing metadatas keys: {missing}")
    else:
        print(f"   ✓ All required metadatas keys present")

# 4. Check linkage
if docs and emb_count > 0:
    doc = docs[0]
    custom_doc_id = doc.get("custom_doc_id")
    linked_embs = db.document_embedding_private.count_documents({
        "metadatas.custom_doc_id": custom_doc_id
    })
    print(f"\n4. Data Linkage:")
    print(f"   Document: {doc.get('file_name_original')}")
    print(f"   custom_doc_id: {custom_doc_id}")
    print(f"   Linked embeddings: {linked_embs}")
    if linked_embs > 0:
        print(f"   ✓ Linkage working")
    else:
        print(f"   ❌ No embeddings linked")

# 5. Check GCS paths
if docs:
    doc = docs[0]
    extracted_images = doc.get("extracted_image_gcp_paths", {})
    print(f"\n5. GCS Path Structure:")
    print(f"   file_path: {doc.get('file_path')}")
    print(f"   dir_path_gcp: {doc.get('dir_path_gcp')}")
    print(f"   extracted_image_gcp_paths: {len(extracted_images)} pages")
    if extracted_images:
        sample_page = list(extracted_images.keys())[0]
        sample_path = extracted_images[sample_page]
        print(f"   Sample image (page {sample_page}): {sample_path}")
        if "roshn-gpt-document-images" in sample_path:
            print(f"   ✓ Using RoshnGPT path format")
        else:
            print(f"   ⚠ Old path format detected")

print("\n" + "="*60)
success = gpt_count > 0 and len(docs) > 0 and emb_count > 0
if success:
    print("✓ RoshnGPT Integration VALIDATED")
else:
    print("❌ RoshnGPT Integration INCOMPLETE")
print("="*60)
```

**Testing Checklist:**
- [ ] custom-gpt-dim: Create GPT succeeds
- [ ] document-dim: Upload populates all 13 new fields
- [ ] referenceId linkage: document.referenceId = custom_gpt_id
- [ ] custom_doc_id format: {user_id}{timestamp}
- [ ] GCS paths: Documents in roshn-gpt-document-repo/UGPT-...
- [ ] GCS paths: Images in roshn-gpt-document-images/{custom_doc_id}/
- [ ] extracted_image_gcp_paths: Dict populated per page
- [ ] document_embedding_private: Nested metadatas structure
- [ ] Embedding linkage: metadatas.custom_doc_id matches document
- [ ] document_name_id: Matches GPT's vectordb_collection_name
- [ ] Backward compat: doc_embeddings still populated
- [ ] Search: Works on document_embedding_private collection

## Migration Strategy

### For Existing RAG-FL Data

**Option 1: Dual-Write (Recommended)**
- New uploads use RoshnGPT schema
- Old data remains in legacy format
- Both schemas coexist
- Search queries both collections

**Option 2: Backfill Migration**
```python
# scripts/migrate_to_roshngpt.py
# Migrate existing documents to RoshnGPT format
# 1. Create default custom GPT for legacy data
# 2. Generate custom_doc_id for each existing document
# 3. Add referenceId linkage
# 4. Convert doc_embeddings to document_embedding_private
```

**Recommended:** Option 1 (Dual-Write) for Phase 6.2, Option 2 for Phase 7 production migration.

## Dependencies & Prerequisites

### Python Packages
```
# No new packages required
# Existing dependencies sufficient:
# - pymongo
# - google-cloud-storage
# - pydantic
# - requests (for standalone scripts)
```

### Environment Variables
```bash
# Production MongoDB Atlas
MONGODB_ATLAS_URI=mongodb+srv://...
MONGODB_ATLAS_DB=roshngpt

# Production GCS
GCS_BUCKET=vector_embedding_mongodb
GCS_SERVICE_ACCOUNT_KEY_PATH=/path/to/key.json
GCS_PROJECT_ID=your-project-id

# Existing (keep)
GOOGLE_API_KEY=...
EMBEDDING_MODEL=models/gemini-embedding-001
VISION_MODEL=gemini-2.0-flash
```

### Access Requirements
- MongoDB Atlas: Read/write permissions
- GCS: Storage Object Admin role
- IP whitelist: Development machine IP added to Atlas
- VPN: If required for Atlas access

## Timeline Estimate

| Phase | Tasks | Estimated Time |
|-------|-------|----------------|
| Phase 0 | Connection setup, credentials | 2 hours |
| Phase 1 | custom-gpt-dim collection | 3 hours |
| Phase 2 | document-dim schema extension | 4 hours |
| Phase 3 | GCS path migration | 3 hours |
| Phase 4 | Embeddings restructure | 5 hours |
| Phase 5 | Standalone scripts | 3 hours |
| Phase 6 | Testing & validation | 2 hours |
| **TOTAL** | | **22 hours (~3 days)** |

### Suggested Schedule

**Day 1 (Saturday 15 March):**
- Evening: Meeting with Mas Rahmad (Phase 0.1)

**Day 2 (Sunday 16 March):**
- Morning: Connection testing (Phase 0.2-0.3)
- Afternoon: custom-gpt-dim implementation (Phase 1)

**Day 3 (Monday 17 March):**
- Morning: document-dim extension (Phase 2)
- Afternoon: GCS path migration (Phase 3)

**Day 4 (Tuesday 18 March):**
- Morning-Afternoon: Embeddings restructure (Phase 4)
- Late: Standalone scripts (Phase 5)

**Day 5 (Wednesday 19 March):**
- Morning: Testing & validation (Phase 6)
- Afternoon: Documentation & handoff

## Success Criteria

**Phase 0 Success:**
- [ ] MongoDB Atlas connection established
- [ ] GCS bucket accessible
- [ ] Test script runs without errors

**Phase 1 Success:**
- [ ] custom-gpt-dim collection created
- [ ] Sample GPT created via script
- [ ] MongoDB indexes applied

**Phase 2 Success:**
- [ ] DocumentRecord extended with 13 fields
- [ ] Upload endpoint accepts custom_gpt_id
- [ ] referenceId linkage working

**Phase 3 Success:**
- [ ] Files uploaded to RoshnGPT path structure
- [ ] extracted_image_gcp_paths populated
- [ ] GCS bucket structure matches target

**Phase 4 Success:**
- [ ] document_embedding_private collection created
- [ ] Embeddings stored in nested format
- [ ] metadatas structure validates

**Phase 5 Success:**
- [ ] 3 standalone scripts working
- [ ] End-to-end flow: create GPT → upload → embed
- [ ] Scripts output clear success messages

**Phase 6 Success:**
- [ ] Validation script passes all checks
- [ ] Data linkage verified across 3 collections
- [ ] Search queries work on new schema
- [ ] No regressions in existing functionality

## Risks & Mitigations

**Risk 1: MongoDB Atlas credentials delayed**
- Mitigation: Use local MongoDB with RoshnGPT schema for development
- Fallback: Mock collections for testing

**Risk 2: GCS path migration breaks existing UI**
- Mitigation: Maintain backward compatibility in image retrieval
- Fallback: Dual-path resolution (try RoshnGPT format, fallback to old)

**Risk 3: Schema changes break existing search**
- Mitigation: Dual-write to both doc_embeddings and document_embedding_private
- Fallback: Search both collections, merge results

**Risk 4: custom_doc_id format conflicts**
- Mitigation: Validate uniqueness before insert
- Fallback: Add random suffix if collision detected

## Next Steps After Phase 6.2

**Phase 7: Production Deployment**
1. Deploy to Google Cloud Run
2. Set up Cloud SQL for MongoDB (or use Atlas production cluster)
3. Configure Cloud Storage buckets
4. Set up CI/CD pipeline
5. Monitoring & alerting

**Phase 7.1: Advanced Features**
1. RAPTOR hierarchical clustering
2. Multi-modal search (text + image)
3. Citation provenance UI enhancements
4. Document versioning
5. Access control & permissions

## References

**Meeting Artifacts:**
- Meeting transcript: `E:\Work\TMC - Roshn\Meeting\meeting with prasang 15 March 2026\sync with harsh prasang and neha_mp4 Transcript.txt`
- Excalidraw diagram: `ROSHNGPT - v2.png`
- JSON structure examples: `Json in Excalidraw.txt`
- Meeting notes: `Meeting sync for json structure format.txt`

**Related Phase Summaries:**
- Phase 3: Per-Page Analysis & Element Detection
- Phase 4: Next.js Observability UI
- Phase 5: Citation Engine & Provenance API
- Phase 6: Search & Retrieval API
- Phase 6.1: MarkItDown Comparison

**Key Contacts:**
- Harsh Ratde (RoshnGPT Lead)
- Prasang (Team Member)
- Neha (Team Member)
- Mas Rahmad (Infrastructure Setup)

## Appendix: Quick Reference

### Collection Names
```
Current RAG-FL:
- documents
- page_profiles
- doc_embeddings
- file_ledger
- citation_cache

RoshnGPT Target:
- custom-gpt-dim
- document-dim (extends documents)
- document_embedding_private (replaces doc_embeddings)
```

### Field Mapping

**documents → document-dim:**
```
doc_id → doc_id (keep for backward compat)
       + custom_doc_id (new format)
       + referenceId (MANDATORY link to custom_gpt_id)
       + user_id
       + file_name_original
       + file_name
       + dir_path_gcp
       + file_path
       + source_dep
       + extracted_image_gcp_paths
       + num_chunks
       + isDocumentEmbeded
       + fileLoaded
```

**doc_embeddings → document_embedding_private:**
```
chunk_text → documents
page_number → metadatas.page (0-indexed)
doc_id → metadatas.mongo_doc_ObjectId
       + metadatas.custom_doc_id
       + custom_gpt_id (top-level)
       + document_name_id (top-level)
embedding[] → embedding[] (unchanged)
```

### CLI Commands

```bash
# Create custom GPT
python scripts/create_custom_gpt.py --config config/custom_gpt_config.yaml

# Upload document
python scripts/upload_document.py \
  --file path/to/doc.pdf \
  --custom-gpt-id <gpt_id> \
  --user-id <user_id> \
  --user-name "Name"

# Embed document
python scripts/embed_document.py --custom-doc-id <custom_doc_id>

# Validate integration
python scripts/validate_roshngpt_integration.py

# Test connections
python scripts/test_connection.py
```

### MongoDB Queries

```javascript
// Check custom GPT
db["custom-gpt-dim"].findOne()

// Check document linkage
db.documents.findOne(
  {referenceId: {$exists: true}},
  {referenceId: 1, custom_doc_id: 1, user_id: 1}
)

// Check embeddings structure
db.document_embedding_private.findOne(
  {},
  {documents: 1, metadatas: 1, custom_gpt_id: 1, document_name_id: 1}
)

// Verify linkage
const doc = db.documents.findOne({referenceId: {$exists: true}})
db.document_embedding_private.countDocuments({
  "metadatas.custom_doc_id": doc.custom_doc_id
})
```

### GCS Path Examples

```
Document:
gs://vector_embedding_mongodb/roshn-gpt-document-repo/UGPT-C8DVEvqJlze9ETKEIWpJ83KQHjo2-kurnia-rag-embedding/Churn_EDA_Report_C8DVEvqJlze9ETKEIWpJ83KQHjo21710537600000.pdf

Images:
gs://vector_embedding_mongodb/roshn-gpt-document-images/C8DVEvqJlze9ETKEIWpJ83KQHjo21710537600000/page_1.png
gs://vector_embedding_mongodb/roshn-gpt-document-images/C8DVEvqJlze9ETKEIWpJ83KQHjo21710537600000/page_2.png
gs://vector_embedding_mongodb/roshn-gpt-document-images/C8DVEvqJlze9ETKEIWpJ83KQHjo21710537600000/page_3.png
```

---

**Document Version:** 1.0
**Last Updated:** 15 March 2026
**Author:** Kurnia A. Ra'if
**Status:** Ready for Implementation
