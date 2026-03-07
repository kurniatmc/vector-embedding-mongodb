# Phase X Summary
> Auto-generate this at the end of each phase.
> Save to docs/phase_summaries/phase_X_summary.md

---

## Phase [X] — [Phase Name]
**Completed:** [date]
**Status:** ✅ Complete
**FORCE_MIXED_MODE at time of testing:** [true/false]

---

## 1. Files Created

| File | Description |
|---|---|
| `services/rag-fl/pipeline.py` | Main entry point — CLI + FastAPI |
| `services/rag-fl/classifier.py` | Per-page classification logic |
| ... | ... |

---

## 2. Schema Validation

> Harsh requirement: schema must be aligned before and after implementation.

| Collection | Fields Present | Missing Fields | Notes |
|---|---|---|---|
| doc_embeddings | chunk_id, doc_id, page_number, ... | none | All canonical fields ✅ |
| documents | content_hash, report_period, ... | none | Chrono metadata ✅ |
| page_profiles | doc_id, page_number, page_type, ... | none | ✅ |

---

## 3. How to Verify

```bash
# Verify embeddings
docker compose exec mongo mongosh ragfl --eval "db.doc_embeddings.countDocuments({})"
docker compose exec mongo mongosh ragfl --eval "db.doc_embeddings.findOne({chunk_type:'multimodal'})"

# Verify page profiles
docker compose exec mongo mongosh ragfl --eval "db.page_profiles.countDocuments({})"

# Verify chrono metadata
docker compose exec mongo mongosh ragfl --eval "db.documents.findOne({},{content_hash:1,report_period:1,period_confidence:1})"

# Verify no duplicates re-embedded
docker compose exec mongo mongosh ragfl --eval "db.documents.find({is_duplicate_of:{$ne:null}}).count()"
```

---

## 4. Test Results

| Test | Input | Expected | Actual | Pass? |
|---|---|---|---|---|
| Classify only | Churn_EDA_Report.pdf | 9 page_profiles, 0 API calls | ... | ✅/❌ |
| Full pipeline | Churn_EDA_Report.pdf | Page 8 multimodal, gcs_image_path set | ... | ✅/❌ |
| Comparison: Excel | Churn_Jan2025.xlsx | Markdown table, all 15 rows | ... | ✅/❌ |
| Comparison: PDF embedded | churn_table_embedded.pdf | Markdown table, structure intact | ... | ✅/❌ |
| Comparison: PDF screenshot | churn_table_screenshot.pdf | Gemini Vision description, mentions columns | ... | ✅/❌ |
| Dedup check | Upload same file twice | Second upload: is_duplicate_of set | ... | ✅/❌ |
| Chrono metadata | January 2025 report | report_period="2025-01", confidence=high/medium | ... | ✅/❌ |
| ROSHN Part 01 | 15 pages | Pages 1-2 skip, multimodal pages embedded | ... | ✅/❌ |

---

## 5. Comparison Test Results (Harsh's explicit request)

**Test: same table data across three file types**

| Metric | Excel native | PDF embedded table | PDF screenshot |
|---|---|---|---|
| Extraction method | pdfplumber Markdown | pdfplumber Markdown | Gemini Vision description |
| Column count detected | 10/10 | ?/10 | N/A (text desc) |
| Row count detected | 15/15 | ?/15 | N/A (text desc) |
| Numerical values accurate | ✅ | ?% | Gemini mentions key numbers? |
| Embedding similarity (Excel vs PDF) | baseline | cosine: ? | cosine: ? |
| Notes | Source of truth | Any merged cell issues? | Gemini description quality? |

---

## 6. Gemini API Usage

| Document | Gemini Vision Calls | text-embedding-004 Calls | Notes |
|---|---|---|---|
| Churn_EDA_Report.pdf (9 pages) | ? | ? | |
| guidelines_part_01_pages_1-15.pdf | ? | ? | |
| Titanic_data_pdf_1.pdf | ? | ? | |
| guidelines_part_02_pages_16-30.pdf | ? | ? | |
| Fraud Literature Review | ? | ? | |
| TOTAL | ? | ? | Estimated cost: $ ? |

---

## 7. Chronological Metadata Results

| File | report_period | period_confidence | extraction_method |
|---|---|---|---|
| guidelines_part_01_pages_1-15.pdf | null | none | n/a |
| Churn_EDA_Report.pdf | null | none | n/a |
| Apartment_Specialists_Churn_Jan2025.xlsx | 2025-01 | high | filename |
| [monthly report with date in name] | 2025-01 | high | filename |

---

## 8. Deviations from ARCHITECTURE.md

| Decision | Architecture says | What was implemented | Reason |
|---|---|---|---|
| [none] | | | |

---

## 9. Known Limitations / TODOs

- [ ] [TODO 1]
- [ ] [TODO 2]

---

## 10. Prerequisites for Next Phase

Before starting Phase [X+1]:
- [ ] `docker compose ps` → all containers healthy
- [ ] `db.doc_embeddings.countDocuments({})` → > 0
- [ ] `db.doc_embeddings.findOne({chunk_type:'multimodal'})` → gcs_image_path present
- [ ] `db.page_profiles.countDocuments({})` → > 0
- [ ] Comparison test documented in section 5 above
- [ ] phase_[X]_summary.md committed to docs/phase_summaries/
