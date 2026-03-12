"""scripts/investigate_chunks.py — chunk type/image investigation for all files"""
import os, sys
sys.path.insert(0, ".")
os.environ["MONGODB_URI"] = "mongodb://localhost:27017/ragfl?directConnection=true"

from shared.utils.mongo_client import documents as docs_col, doc_embeddings as emb_col

PYMUPDF_FILTER = {"$or": [{"processing_method": "pymupdf"}, {"processing_method": {"$exists": False}}, {"processing_method": None}]}

FILES = ["Titanic_data_pdf_1.pdf", "Word_Titanic_data_pdf_1.docx", "PPT_Titanic_data_pdf_1.pptx"]

for fname in FILES:
    doc = docs_col().find_one({"filename": fname})
    if not doc:
        print(f"NOT FOUND: {fname}\n")
        continue

    chunks = list(emb_col().find(
        {"doc_id": doc["doc_id"], **PYMUPDF_FILTER},
        {"chunk_type": 1, "page_number": 1, "gcs_image_path": 1,
         "chunk_text": 1, "format_provenance": 1, "section_title": 1}
    ))

    types = {}
    has_img = 0
    for c in chunks:
        t = c.get("chunk_type", "?")
        types[t] = types.get(t, 0) + 1
        if c.get("gcs_image_path"):
            has_img += 1

    print(f"=== {fname} ===")
    print(f"  original_format  : {doc['original_format']}")
    print(f"  format_provenance: {doc.get('format_provenance', {})}")
    print(f"  gcs_path         : {doc.get('gcs_path', '')}")
    print(f"  gcs_original_path: {doc.get('gcs_original_path', 'None')}")
    print(f"  pymupdf chunks   : {len(chunks)} | types: {types} | with_image: {has_img}")
    print()

    # Show per-page breakdown
    for pg in sorted(set(c["page_number"] for c in chunks)):
        pg_chunks = [c for c in chunks if c["page_number"] == pg]
        for c in pg_chunks:
            img = c.get("gcs_image_path", "")
            txt = (c.get("chunk_text") or "")[:60].replace("\n", " ")
            print(f"  pg{pg:2d} {c['chunk_type']:<15s} img={'Y' if img else 'N'} {txt}")
    print()
