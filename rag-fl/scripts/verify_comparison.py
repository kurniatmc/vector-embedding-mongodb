"""scripts/verify_comparison.py — verify comparison API correctness"""
import os, sys, json, urllib.request

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ["MONGODB_URI"] = "mongodb://localhost:27017/ragfl?directConnection=true"

from shared.utils.mongo_client import documents as docs_col

FILES = [
    "Word_Titanic_data_pdf_1.docx",
    "PPT_Titanic_data_pdf_1.pptx",
    "multiple sheets data.xlsx",
]

for fname in FILES:
    doc = docs_col().find_one({"filename": fname})
    if not doc:
        print(f"NOT FOUND: {fname}")
        continue

    url = f"http://localhost:8004/comparison/{doc['doc_id']}?limit=3"
    with urllib.request.urlopen(url) as r:
        d = json.loads(r.read())

    print(f"=== {fname} ===")
    print(f"  method_a_label : {d['method_a_label']}")
    print(f"  method_b_label : {d['method_b_label']}")
    print(f"  pymupdf total  : {d['pymupdf']['total_chunks']} | types: {d['pymupdf']['type_breakdown']}")
    print(f"  markitdown total: {d['markitdown']['total_chunks']} | types: {d['markitdown']['type_breakdown']}")

    for c in d["pymupdf"]["chunks"][:1]:
        has_img = bool(c.get("gcs_image_path"))
        dims    = c.get("embedding_dims", "?")
        bbox    = bool(c.get("bounding_box"))
        print(f"  pymupdf[0]: type={c['chunk_type']} img={has_img} dims={dims} bbox={bbox}")
        print(f"    text={c['chunk_text'][:60]}")

    for c in d["markitdown"]["chunks"][:1]:
        dims = c.get("embedding_dims", "?")
        print(f"  mkd[0]    : type={c['chunk_type']} dims={dims} prov={c.get('format_provenance',{})}")
        print(f"    text={c['chunk_text'][:60]}")
    print()
