#!/usr/bin/env python3
"""
scripts/cleanup_mongodb.py
Delete all MongoDB documents EXCEPT the 3 baseline comparison files.
Run from the rag-fl/ project root.

Keeps:
  - CustomerChurn_Jan2025.xlsx
  - PureTable_CustomerChurn_Jan2025.pdf   (matches filename containing this string)
  - SS_CustomerChurn_Jan2025.pdf          (matches filename containing this string)

Usage:
  python scripts/cleanup_mongodb.py           # dry-run (shows what would be deleted)
  python scripts/cleanup_mongodb.py --yes     # actually delete
"""
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

# Host-mode override (same as pipeline.py)
if not os.path.exists("/.dockerenv"):
    os.environ["MONGODB_URI"] = "mongodb://localhost:27017/ragfl?directConnection=true"

from shared.utils.mongo_client import (
    doc_embeddings as get_embeddings_col,
    documents as get_documents_col,
    page_profiles as get_profiles_col,
)

# ── Baseline filenames to KEEP ────────────────────────────────────────────────
KEEP_FILENAMES = [
    "CustomerChurn_Jan2025.xlsx",
    "PureTable_CustomerChurn_Jan2025.pdf",
    "SS_CustomerChurn_Jan2025.pdf",
]


def main():
    dry_run = "--yes" not in sys.argv
    if dry_run:
        print("DRY RUN mode — pass --yes to actually delete\n")

    docs_col = get_documents_col()
    emb_col = get_embeddings_col()
    prof_col = get_profiles_col()

    # Fetch all documents
    all_docs = list(docs_col.find({}, {"doc_id": 1, "filename": 1, "status": 1}))
    print(f"Total documents in MongoDB: {len(all_docs)}")

    keep_ids: set[str] = set()
    delete_ids: list[str] = []

    for doc in all_docs:
        filename = doc.get("filename", "")
        if filename in KEEP_FILENAMES:
            keep_ids.add(doc["doc_id"])
            print(f"  KEEP: {filename} ({doc['doc_id'][:8]}…) [{doc.get('status')}]")
        else:
            delete_ids.append(doc["doc_id"])

    print(f"\nFiles to KEEP: {len(keep_ids)}")
    print(f"Files to DELETE: {len(delete_ids)}\n")

    if not delete_ids:
        print("Nothing to delete.")
        return

    # Show what will be deleted
    for doc in all_docs:
        if doc["doc_id"] in delete_ids:
            chunk_count = emb_col.count_documents({"doc_id": doc["doc_id"]})
            print(f"  DELETE: {doc['filename']} ({doc['doc_id'][:8]}…) [{chunk_count} chunks]")

    if dry_run:
        print("\nDry run complete. Pass --yes to delete.")
        return

    print("\nDeleting…")
    for doc_id in delete_ids:
        chunks_deleted = emb_col.delete_many({"doc_id": doc_id}).deleted_count
        profiles_deleted = prof_col.delete_many({"doc_id": doc_id}).deleted_count
        docs_col.delete_one({"doc_id": doc_id})
        print(f"  Deleted doc_id={doc_id[:8]}… ({chunks_deleted} chunks, {profiles_deleted} profiles)")

    print(f"\nCleanup complete. {len(delete_ids)} documents removed.")
    print(f"Remaining: {keep_ids}")


if __name__ == "__main__":
    main()
