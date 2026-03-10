import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.lines as mlines

# Create figure
fig, ax = plt.subplots(1, 1, figsize=(18, 24))
ax.set_xlim(0, 18)
ax.set_ylim(0, 24)
ax.axis('off')

# Title
ax.text(9, 23.5, 'RAG-FL Multimodal Pipeline Architecture',
        ha='center', va='top', fontsize=20, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='lightblue', edgecolor='navy', linewidth=2))

# Color scheme
color_upload = '#E8F5E9'  # Light green
color_classify = '#FFF3E0'  # Light orange
color_chunk = '#E1F5FE'  # Light blue
color_embed = '#F3E5F5'  # Light purple
color_store = '#FFE0B2'  # Light amber
color_multimodal = '#FFCDD2'  # Light red (highlight)

def draw_box(ax, x, y, width, height, text, color, fontsize=10, fontweight='normal'):
    """Draw a rounded box with text"""
    box = FancyBboxPatch((x, y), width, height,
                         boxstyle="round,pad=0.05",
                         facecolor=color, edgecolor='black', linewidth=1.5)
    ax.add_patch(box)
    ax.text(x + width/2, y + height/2, text,
           ha='center', va='center', fontsize=fontsize, fontweight=fontweight,
           wrap=True)

def draw_arrow(ax, x1, y1, x2, y2, label='', color='black'):
    """Draw an arrow between two points"""
    arrow = FancyArrowPatch((x1, y1), (x2, y2),
                           arrowstyle='->', mutation_scale=20,
                           color=color, linewidth=2)
    ax.add_patch(arrow)
    if label:
        mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
        ax.text(mid_x + 0.3, mid_y, label, fontsize=8,
               bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8))

# ============ LEVEL 1: HIGH-LEVEL FLOW ============
y_start = 21

# Upload
draw_box(ax, 0.5, y_start, 2.5, 1, 'FILE UPLOAD\n(UI/API)', color_upload, fontsize=11, fontweight='bold')
draw_arrow(ax, 3.2, y_start + 0.5, 4.3, y_start + 0.5)

# Ingestion
draw_box(ax, 4.5, y_start, 2.5, 1, 'INGESTION\nService :8001\n• Format detection\n• Dedup (SHA-256)\n• GCS upload',
         color_upload, fontsize=9)
draw_arrow(ax, 7.2, y_start + 0.5, 8.3, y_start + 0.5, 'doc_id')

# Pipeline
draw_box(ax, 8.5, y_start, 2.5, 1, 'PIPELINE\nService :8004\nCLASSIFY → CHUNK\n→ EMBED → STORE',
         color_classify, fontsize=10, fontweight='bold')
draw_arrow(ax, 11.2, y_start + 0.5, 12.3, y_start + 0.5)

# Search
draw_box(ax, 12.5, y_start, 2.5, 1, 'SEARCH API\n:8004/search\n• Redis cache\n• Citation labels',
         color_store, fontsize=9)
draw_arrow(ax, 15.2, y_start + 0.5, 16.3, y_start + 0.5)

# UI
draw_box(ax, 16.5, y_start, 1.3, 1, 'UI\n:3001', color_store, fontsize=10, fontweight='bold')

# ============ LEVEL 2: CLASSIFIER DETAIL ============
y_classify = 18

ax.text(9, y_classify + 1.3, 'CLASSIFIER (classifier.py) — Zero Gemini API Cost',
        ha='center', fontsize=12, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='lightyellow', edgecolor='orange', linewidth=2))

# Step 1: Tables
draw_box(ax, 0.5, y_classify, 5, 1,
         'STEP 1: TABLE DETECTION\n'
         '• LINES strategy (reliable, can suppress visuals)\n'
         '• Whitespace alignment (soft, never suppresses)\n'
         '• Text+lines (soft, runs AFTER visual detection)',
         color_classify, fontsize=8)

draw_arrow(ax, 5.7, y_classify + 0.5, 6.3, y_classify + 0.5)

# Step 2A: Images
draw_box(ax, 6.5, y_classify + 0.3, 5, 0.7,
         'STEP 2A: IMAGE XOBJECTS (Phase 3D)\n'
         'get_images() → Each XObject SEPARATE (no clustering)\n'
         'Filter: >=0.5% page area, not inside LINES tables',
         color_multimodal, fontsize=8, fontweight='bold')

draw_arrow(ax, 11.7, y_classify + 0.65, 12.3, y_classify + 0.65)

# Step 2B: Drawings
draw_box(ax, 6.5, y_classify - 0.5, 5, 0.7,
         'STEP 2B: VECTOR DRAWINGS\n'
         'get_drawings() → cluster (gap=20pt) → dedupe vs images\n'
         'Filter: >=3% page area, not >70% covered by image',
         '#E3F2FD', fontsize=8)

draw_arrow(ax, 11.7, y_classify - 0.15, 12.3, y_classify - 0.15)

# Step 2B': Pixel fallback
draw_box(ax, 6.5, y_classify - 1.3, 5, 0.7,
         'STEP 2B: PIXEL FALLBACK\n'
         'If covered_area <50% AND non_white >20% → full-page visual\n'
         'Catches: Form XObjects, screenshots',
         '#FFF9C4', fontsize=8)

draw_arrow(ax, 11.7, y_classify - 0.95, 12.3, y_classify - 0.95)

# Step 3: Text
draw_box(ax, 12.5, y_classify, 5, 1,
         'STEP 3: TEXT BLOCKS (Phase 3E)\n'
         '• get_text("blocks"), char_count >20\n'
         '• Exclude if center inside table/visual bbox\n'
         '• Exclude if overlap >50% (tables) / >30% (visuals)',
         color_classify, fontsize=8)

# Page Type Derivation
draw_box(ax, 7, y_classify - 2.2, 4, 0.7,
         'PAGE TYPE DERIVATION\n'
         'visual+text/table→mixed | visual only→multimodal\n'
         'table only→table | text only→text | none→skip',
         '#E0E0E0', fontsize=8, fontweight='bold')

# ============ LEVEL 3: CHUNKER DISPATCH ============
y_chunk = 14.5

ax.text(9, y_chunk + 1.3, 'CHUNKER (chunker.py) — Element-Based Dispatch',
        ha='center', fontsize=12, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='lightcyan', edgecolor='teal', linewidth=2))

# Table path
draw_box(ax, 0.5, y_chunk, 3.5, 1,
         'TABLE ELEMENT\n'
         '• Has rows key → chunk_whitespace_table()\n'
         '• No rows → chunk_specific_table()\n'
         '• Output: Markdown table',
         color_chunk, fontsize=9)

draw_arrow(ax, 4.2, y_chunk + 0.5, 5.3, y_chunk + 0.5)

# Visual path (MULTIMODAL HIGHLIGHT)
draw_box(ax, 4.5, y_chunk, 4.5, 1,
         'VISUAL ELEMENT (MULTIMODAL PATH)\n'
         '• render_and_upload_visual_region()\n'
         '• Clip bbox at 2x zoom, trim whitespace\n'
         '• Upload to GCS: {doc_id}.{page}.v{n}\n'
         '• Gemini Vision call (gemini-2.0-flash)',
         color_multimodal, fontsize=9, fontweight='bold')

draw_arrow(ax, 9.2, y_chunk + 0.5, 10.3, y_chunk + 0.5, 'vision')

# Text path
draw_box(ax, 10.5, y_chunk, 3.5, 1,
         'TEXT ELEMENT\n'
         '• chunk_text_page(exclude_rects)\n'
         '• Heading-bounded 500-800 tokens\n'
         '• Phase 3E: AND logic (center AND >70% overlap)',
         color_chunk, fontsize=9)

draw_arrow(ax, 14.2, y_chunk + 0.5, 15.3, y_chunk + 0.5)

# Chunks output
draw_box(ax, 15.5, y_chunk, 2, 1,
         'CHUNKS\nList[ChunkRecord]\n• chunk_text\n• gcs_image_path\n• bbox',
         color_chunk, fontsize=9, fontweight='bold')

# ============ LEVEL 4: EMBEDDER ============
y_embed = 12

ax.text(9, y_embed + 1.3, 'EMBEDDER (embedder.py) — Asymmetric Task Types',
        ha='center', fontsize=12, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='#F3E5F5', edgecolor='purple', linewidth=2))

# Multimodal chunk
draw_box(ax, 0.5, y_embed, 4.5, 0.9,
         'MULTIMODAL CHUNK\n'
         'chunk_text = Gemini Vision description\n'
         'gcs_image_path = gs://bucket/{doc_id}.{page}.v{n}',
         color_multimodal, fontsize=9, fontweight='bold')

draw_arrow(ax, 5.2, y_embed + 0.45, 6.3, y_embed + 0.45)

# Table chunk
draw_box(ax, 0.5, y_embed - 1.2, 4.5, 0.9,
         'TABLE CHUNK\n'
         'chunk_text = Markdown table\n'
         'gcs_image_path = null',
         color_chunk, fontsize=9)

draw_arrow(ax, 5.2, y_embed - 0.75, 6.3, y_embed - 0.75)

# Text chunk
draw_box(ax, 0.5, y_embed - 2.4, 4.5, 0.9,
         'TEXT CHUNK\n'
         'chunk_text = extracted text\n'
         'gcs_image_path = null',
         color_chunk, fontsize=9)

draw_arrow(ax, 5.2, y_embed - 1.95, 6.3, y_embed - 1.95)

# Embedding process
draw_box(ax, 6.5, y_embed - 1.5, 5, 2.5,
         'BATCH EMBEDDING\n'
         'gemini-embedding-001\n'
         'Task type: RETRIEVAL_DOCUMENT\n'
         'Output: 768-dim float vector\n\n'
         'Batch size: 100 chunks\n'
         'Rate limit: handled by SDK',
         color_embed, fontsize=9, fontweight='bold')

draw_arrow(ax, 11.7, y_embed - 0.3, 12.8, y_embed - 0.3)

# Storage
draw_box(ax, 13, y_embed - 1.5, 4.5, 2.5,
         'MONGODB STORAGE\n'
         'doc_embeddings{}\n'
         '• chunk_id (UUID)\n'
         '• doc_id, page_number\n'
         '• chunk_type, chunk_text\n'
         '• embedding [768 floats]\n'
         '• gcs_image_path\n'
         '• bounding_box',
         color_store, fontsize=9, fontweight='bold')

# ============ LEVEL 5: SEARCH FLOW ============
y_search = 8

ax.text(9, y_search + 1.3, 'SEARCH FLOW (search.py) — Query-Time',
        ha='center', fontsize=12, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='#FFE0B2', edgecolor='darkorange', linewidth=2))

# User query
draw_box(ax, 0.5, y_search, 3, 0.8,
         'USER QUERY\n"churn rate for fiber optic?"',
         '#FFF9C4', fontsize=10, fontweight='bold')

draw_arrow(ax, 3.7, y_search + 0.4, 4.8, y_search + 0.4)

# Query embedding
draw_box(ax, 5, y_search, 3.5, 0.8,
         'EMBED QUERY\n'
         'gemini-embedding-001\n'
         'Task: RETRIEVAL_QUERY (asymmetric!)',
         color_embed, fontsize=9)

draw_arrow(ax, 8.7, y_search + 0.4, 9.8, y_search + 0.4)

# Vector search
draw_box(ax, 10, y_search, 3.5, 0.8,
         'VECTOR SEARCH\n'
         'Cosine similarity vs all embeddings\n'
         'Apply filters (doc_ids, format, period)',
         color_store, fontsize=9)

draw_arrow(ax, 13.7, y_search + 0.4, 14.8, y_search + 0.4)

# Results
draw_box(ax, 15, y_search, 2.5, 0.8,
         'RESULTS + CITATIONS\n'
         'score, chunk_text\n'
         'citation labels\n'
         'deep links',
         color_store, fontsize=9, fontweight='bold')

# Redis cache (off to the side)
draw_box(ax, 10, y_search - 1.3, 3.5, 0.6,
         'REDIS CACHE (1hr TTL)\n'
         'Key: sha256(query+filters)',
         '#FFCCBC', fontsize=8)

draw_arrow(ax, 11.75, y_search, 11.75, y_search - 0.7, color='red')
draw_arrow(ax, 11.75, y_search - 0.7, 11.75, y_search, color='red')

# ============ LEVEL 6: KEY METRICS ============
y_metrics = 5.5

ax.text(9, y_metrics + 1.3, 'KEY ARCHITECTURAL DECISIONS (Phase 3D/3E - 2026-03-10)',
        ha='center', fontsize=12, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='#E8F5E9', edgecolor='green', linewidth=2))

metrics_text = """
Phase 3D: Separate Images from Drawings
  Before: Combined pool → cluster (gap=20pt) → try split → often failed
  After: Images NEVER cluster | Drawings cluster → dedupe against images
  Result: Pivot tables on page 3 now detected as separate elements

Phase 3E: Text Extraction Quality Fixes
  • Pixel fallback threshold: 0.15 → 0.20 (reduces false positives)
  • Bidirectional overlap check (prevents large wrapper false-positive tables)
  • Chunker AND logic: skip text ONLY if center inside AND overlap >70%
  • Pipeline selective exclude: only LINES tables + visuals (not soft tables)

Zero Gemini Cost at Classification Stage
  • Classification = free (pdfplumber + PyMuPDF only)
  • Gemini Vision called only for multimodal pages (after classification)
  • Typical 15-page doc: ~3-5 multimodal pages → 3-5 Gemini Vision calls

Asymmetric Embedding (MANDATORY)
  • Storage: RETRIEVAL_DOCUMENT task type
  • Query: RETRIEVAL_QUERY task type
  • Mixing these degrades retrieval quality significantly
"""

ax.text(0.5, y_metrics + 0.5, metrics_text, fontsize=9, verticalalignment='top',
        bbox=dict(boxstyle='round,pad=0.8', facecolor='white', edgecolor='gray', linewidth=1.5))

# ============ LEVEL 7: STATISTICS ============
y_stats = 1.5

stats_box1 = """
PERFORMANCE
• Upload: <1s
• Classification: 2-3s
• Embedding (22 chunks): 1-2s
• Search (cached): <50ms
• Search (uncached): 200-500ms
"""

stats_box2 = """
STORAGE
• documents{}: metadata + status
• page_profiles{}: detected_elements
• doc_embeddings{}: chunks + 768-dim vectors
• citation_cache{}: 1hr TTL
"""

stats_box3 = """
FILTERS
• doc_ids (explicit list)
• format (pdf, xlsx, yaml)
• report_period (YYYY-MM)
• report_series (category)
• include_multimodal (bool)
"""

ax.text(1, y_stats, stats_box1, fontsize=8, verticalalignment='top',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#E3F2FD', edgecolor='blue'))

ax.text(6.5, y_stats, stats_box2, fontsize=8, verticalalignment='top',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#FFF3E0', edgecolor='orange'))

ax.text(12, y_stats, stats_box3, fontsize=8, verticalalignment='top',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#F3E5F5', edgecolor='purple'))

# Footer
ax.text(9, 0.3, 'Generated: 2026-03-10 | Version: 6.0.0 | For: Harsh Ratde → Kurnia Walkthrough',
        ha='center', fontsize=9, style='italic', color='gray')

plt.tight_layout()
output_path = 'docs/phase_summaries/multimodal_pipeline_flowchart.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"Flowchart saved: {output_path}")
