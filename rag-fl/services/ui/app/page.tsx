"use client";

import React, { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

// ── API base URLs ─────────────────────────────────────────────────────────────
const RAG_FL = process.env.NEXT_PUBLIC_RAG_FL_API || "http://localhost:8004";
const INGEST = process.env.NEXT_PUBLIC_INGESTION_API || "http://localhost:8001";

// ── Types ─────────────────────────────────────────────────────────────────────
interface Doc {
  doc_id: string;
  filename: string;
  original_format: string;
  total_pages: number;
  chunk_count: number;
  status: string;
  report_period?: string;
}

interface PageProfile {
  page_number: number;
  page_type: string;
  chunk_count: number;
  text_ratio?: number;
  image_ratio?: number;
  has_tables?: boolean;
}

interface Chunk {
  chunk_id: string;
  chunk_type: string;
  chunk_text: string;
  chunk_index: number;
  section_title?: string;
  gcs_image_path?: string;
  embedding_dims: number;
  format_provenance?: Record<string, unknown>;
  bounding_box?: { x0: number; y0: number; x1: number; y1: number };
}

interface SearchResult {
  chunk_id: string;
  chunk_type: string;
  chunk_text: string;
  page_number: number;
  section_title?: string;
  score: number;
  gcs_image_path?: string;
}

interface ComparisonChunk {
  chunk_id: string;
  chunk_type: string;
  chunk_text: string;
  page_number: number;
  section_title?: string;
  chunk_index: number;
  format_provenance?: Record<string, unknown>;
  gcs_image_path?: string;
  processing_method?: string;
  bounding_box?: { x0: number; y0: number; x1: number; y1: number };
  embedding_dims?: number;
  embedding_model?: string;
}

interface MethodComparisonData {
  doc_id: string;
  filename: string;
  original_format: string;
  method_a_label: string;   // "openpyxl" | "Gotenberg → PDF" | etc.
  method_b_label: string;   // "Direct DOCX Read" | "Direct Excel Read" | etc.
  pymupdf: {
    total_chunks: number;
    chunks_shown: number;
    type_breakdown: Record<string, number>;
    chunks: ComparisonChunk[];
  };
  markitdown: {
    total_chunks: number;
    chunks_shown: number;
    type_breakdown: Record<string, number>;
    chunks: ComparisonChunk[];
  };
}

interface ComparisonSearchResult {
  chunk_id: string;
  chunk_type: string;
  chunk_text: string;
  page_number: number;
  section_title?: string;
  score: number;
  doc_id: string;
  filename?: string;
  processing_method?: string;
}

// ── Image URL helper (Phase 3B — parses .v{n} suffix from gcs_image_path) ────
function gcsImageUrl(
  gcsPath: string | undefined,
  docId: string,
  pageNum: number
): string {
  const base = `${RAG_FL}/image/${docId}/${pageNum}`;
  if (!gcsPath) return base;
  const key = gcsPath.split("/").pop() ?? "";
  const vMatch = key.match(/\.v(\d+)$/);
  if (!vMatch) return base;
  return `${base}?v=${vMatch[1]}`;
}

// ── Method comparison constants & helpers ─────────────────────────────────────
// Baseline files are reserved for FORMAT comparison only — never show method comparison.
const BASELINE_FILENAMES = new Set([
  "CustomerChurn_Jan2025.xlsx",
  "PureTable_CustomerChurn_Jan2025.pdf",
  "SS_CustomerChurn_Jan2025.pdf",
]);

// Formats where MarkItDown comparison is supported (Office files only)
const OFFICE_FORMATS = new Set(["xlsx", "xls", "docx", "pptx", "csv"]);

function getMethodALabel(format: string): string {
  const labels: Record<string, string> = {
    xlsx: "openpyxl",
    xls:  "openpyxl",
    docx: "Gotenberg → PDF",
    pptx: "Gotenberg → PDF",
    csv:  "pandas/csv",
    yaml: "PyYAML",
    yml:  "PyYAML",
  };
  return labels[format] ?? "Current Pipeline";
}

function getMethodBLabel(format: string): string {
  const labels: Record<string, string> = {
    xlsx: "Direct Excel Read",
    xls:  "Direct Excel Read",
    docx: "Direct DOCX Read",
    pptx: "Direct PPTX Read",
    csv:  "Direct CSV Read",
    yaml: "Direct YAML Read",
    yml:  "Direct YAML Read",
  };
  return labels[format] ?? "MarkItDown";
}

function shouldAutoGoToMethodComparison(
  doc: Doc,
  stats: Record<string, { pymupdf: number; markitdown: number }>
): boolean {
  if (BASELINE_FILENAMES.has(doc.filename)) return false;
  if (!OFFICE_FORMATS.has(doc.original_format)) return false;
  const s = stats[doc.doc_id];
  return !!(s && s.markitdown > 0);
}

// ── Comparison group helpers ──────────────────────────────────────────────────
// Strip format-specific prefixes/suffixes to find the base document name.
// Works for any naming convention — not hardcoded to specific filenames.
function normalizeBaseName(filename: string): string {
  let name = filename.replace(/\.[^.]+$/, ""); // strip extension
  // Remove format-indicator prefixes (case-insensitive)
  name = name.replace(/^(PureTable_|SS_|Table_|Screenshot_|Scanned_|Pure_|Embedded_)/i, "");
  // Remove format-indicator suffixes
  name = name.replace(/[_-]?(Table|Screenshot|Pure|Embedded|PureTable|SS|Scanned|Image|Copy)$/i, "");
  return name.toLowerCase().trim();
}

function detectComparisonGroups(docs: Doc[]): Map<string, Doc[]> {
  const groups = new Map<string, Doc[]>();
  for (const doc of docs) {
    const base = normalizeBaseName(doc.filename);
    if (!groups.has(base)) groups.set(base, []);
    groups.get(base)!.push(doc);
  }
  const result = new Map<string, Doc[]>();
  for (const [base, group] of groups) {
    if (group.length >= 2) result.set(base, group);
  }
  return result;
}

// ── Visual content keyword detection ─────────────────────────────────────────
const VISUAL_KEYWORDS = [
  "flow", "diagram", "architecture", "process", "pipeline", "workflow",
  "chart", "graph", "figure", "illustration", "plot", "heatmap",
  "scatter", "histogram", "bar chart", "pie chart", "boxplot", "violin",
  "network", "schematic", "layout", "map",
];

function isVisualContent(text: string): boolean {
  const lower = text.toLowerCase();
  return VISUAL_KEYWORDS.some((kw) => lower.includes(kw));
}

// ── Styling helpers ───────────────────────────────────────────────────────────
function pageTypeCls(type: string): string {
  const m: Record<string, string> = {
    text: "bg-blue-700 text-blue-100",
    table: "bg-green-700 text-green-100",
    multimodal: "bg-purple-700 text-purple-100",
    full_page_image: "bg-violet-700 text-violet-100",
    mixed: "bg-orange-600 text-orange-100",
    skip: "bg-slate-600 text-slate-400",
    structured_text: "bg-cyan-700 text-cyan-100",
  };
  return m[type] ?? "bg-slate-600 text-slate-300";
}

function statusCls(status: string): string {
  const m: Record<string, string> = {
    UPLOADED: "bg-yellow-800 text-yellow-200",
    PROCESSING: "bg-blue-700 text-blue-100 animate-pulse",
    EMBEDDED: "bg-green-800 text-green-200",
    FAILED: "bg-red-800 text-red-200",
  };
  return m[status] ?? "bg-slate-700 text-slate-300";
}

function chunkIcon(type: string): string {
  return { text: "T", table: "≡", multimodal: "▣", full_page_image: "⊞" }[type] ?? "?";
}

// ── Markdown rendering: table elements ───────────────────────────────────────
// Used for both table chunks and inline tables inside text/multimodal chunks.
const mdTableComponents: Components = {
  table: function MdTable({ children }) {
    return (
      <div className="overflow-auto max-h-72 rounded border border-slate-700">
        <table className="w-full text-xs border-collapse">{children}</table>
      </div>
    );
  },
  thead: function MdThead({ children }) {
    return <thead className="sticky top-0 z-10">{children}</thead>;
  },
  th: function MdTh({ children }) {
    return (
      <th className="border border-slate-600 px-2 py-1.5 bg-green-900/50 text-green-200 text-left whitespace-nowrap font-semibold">
        {children}
      </th>
    );
  },
  td: function MdTd({ children }) {
    return (
      <td className="border border-slate-600 px-2 py-1 text-slate-300 whitespace-nowrap">
        {children}
      </td>
    );
  },
  tr: function MdTr({ children }) {
    return <tr className="odd:bg-slate-800/50 even:bg-slate-900/60">{children}</tr>;
  },
  tbody: function MdTbody({ children }) {
    return <tbody>{children}</tbody>;
  },
};

// ── Markdown rendering: full text (headings, paragraphs, lists + tables) ─────
const mdTextComponents: Components = {
  ...mdTableComponents,
  h1: function MdH1({ children }) {
    return <h1 className="text-sm font-bold text-slate-100 mt-3 mb-1">{children}</h1>;
  },
  h2: function MdH2({ children }) {
    return <h2 className="text-xs font-bold text-slate-200 mt-2 mb-1">{children}</h2>;
  },
  h3: function MdH3({ children }) {
    return <h3 className="text-xs font-semibold text-slate-300 mt-2 mb-1">{children}</h3>;
  },
  p: function MdP({ children }) {
    return <p className="text-xs text-slate-300 leading-relaxed mb-2">{children}</p>;
  },
  ul: function MdUl({ children }) {
    return <ul className="text-xs text-slate-300 list-disc list-outside pl-4 mb-2 space-y-0.5">{children}</ul>;
  },
  ol: function MdOl({ children }) {
    return <ol className="text-xs text-slate-300 list-decimal list-outside pl-4 mb-2 space-y-0.5">{children}</ol>;
  },
  li: function MdLi({ children }) {
    return <li className="text-slate-300">{children}</li>;
  },
  strong: function MdStrong({ children }) {
    return <strong className="font-semibold text-slate-100">{children}</strong>;
  },
  em: function MdEm({ children }) {
    return <em className="italic text-slate-300">{children}</em>;
  },
  code: function MdCode({ children }) {
    return (
      <code className="font-mono bg-slate-800 px-1 rounded text-slate-200 text-xs">
        {children}
      </code>
    );
  },
  pre: function MdPre({ children }) {
    return (
      <pre className="bg-slate-900 rounded p-2 overflow-auto text-xs font-mono text-slate-300 mb-2">
        {children}
      </pre>
    );
  },
  blockquote: function MdBlockquote({ children }) {
    return (
      <blockquote className="border-l-2 border-slate-600 pl-3 text-slate-400 italic mb-2">
        {children}
      </blockquote>
    );
  },
};

// ── ChunkCard component ───────────────────────────────────────────────────────
function ChunkCard({
  chunk,
  totalOnPage,
  docId,
  pageNum,
}: {
  chunk: Chunk;
  totalOnPage: number;
  docId: string;
  pageNum: number;
}) {
  const [metaOpen, setMetaOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  function copyId() {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(chunk.chunk_id).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      });
    }
  }

  const showVisualBadge =
    chunk.chunk_type === "multimodal" && isVisualContent(chunk.chunk_text);
  const imageUrl = gcsImageUrl(chunk.gcs_image_path, docId, pageNum);

  return (
    <div className="border border-slate-700/80 rounded overflow-hidden">
      {/* ── Header row: badges + position + dims ── */}
      <div className="flex flex-wrap items-center gap-1.5 px-3 py-2 bg-slate-800/70 border-b border-slate-700/60">
        <span
          className={`px-1.5 py-0.5 rounded text-xs font-medium ${pageTypeCls(chunk.chunk_type)}`}
        >
          {chunkIcon(chunk.chunk_type)} {chunk.chunk_type}
        </span>
        {showVisualBadge && (
          <span className="px-1.5 py-0.5 rounded text-xs bg-violet-900/50 text-violet-300">
            📊 Visual
          </span>
        )}
        <span className="text-xs text-slate-500">
          Chunk {chunk.chunk_index + 1} of {totalOnPage}
        </span>
        {chunk.section_title && (
          <span
            className="text-xs text-slate-400 italic truncate max-w-[150px]"
            title={chunk.section_title}
          >
            {chunk.section_title}
          </span>
        )}
        <span
          className={`ml-auto shrink-0 font-mono text-xs ${
            chunk.embedding_dims === 768 ? "text-green-500" : "text-yellow-500"
          }`}
        >
          {chunk.embedding_dims === 768 ? "768-dim ✓" : `${chunk.embedding_dims}-dim`}
        </span>
      </div>

      {/* ── Sub-header: chunk ID + metadata toggle ── */}
      <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-800/40 border-b border-slate-700/40">
        <span className="text-xs text-slate-600 shrink-0">ID</span>
        <button
          onClick={copyId}
          title="Click to copy full chunk ID"
          className="font-mono text-xs text-slate-500 hover:text-slate-300 transition-colors truncate"
        >
          {chunk.chunk_id.slice(0, 14)}…
        </button>
        {copied && (
          <span className="text-xs text-green-500 shrink-0">copied!</span>
        )}
        <button
          onClick={() => setMetaOpen(!metaOpen)}
          className="ml-auto text-xs text-slate-500 hover:text-slate-300 transition-colors shrink-0"
        >
          {metaOpen ? "▲ Hide metadata" : "▼ Show metadata"}
        </button>
      </div>

      {/* ── Collapsible metadata ── */}
      {metaOpen && (
        <div className="px-3 py-2.5 border-b border-slate-700/40 bg-slate-950/60 space-y-1.5 text-xs">
          {/* Full chunk_id */}
          <div className="flex items-start gap-2">
            <span className="text-slate-600 w-24 shrink-0">chunk_id</span>
            <span className="font-mono text-slate-400 break-all leading-relaxed">
              {chunk.chunk_id}
            </span>
          </div>
          {/* Page */}
          <div className="flex items-center gap-2">
            <span className="text-slate-600 w-24 shrink-0">page</span>
            <span className="text-slate-400">Page {pageNum}</span>
          </div>
          {/* Section title */}
          {chunk.section_title && (
            <div className="flex items-start gap-2">
              <span className="text-slate-600 w-24 shrink-0">section</span>
              <span className="text-slate-400">{chunk.section_title}</span>
            </div>
          )}
          {/* format_provenance */}
          {chunk.format_provenance &&
            Object.keys(chunk.format_provenance).length > 0 && (
              <div className="flex items-start gap-2">
                <span className="text-slate-600 w-24 shrink-0">provenance</span>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(chunk.format_provenance)
                    .filter(([k]) => k !== "rows") // skip large pre-extracted rows array
                    .map(([k, v]) => (
                      <span
                        key={k}
                        className="bg-slate-800 border border-slate-700 px-1.5 py-0.5 rounded text-slate-400"
                      >
                        <span className="text-slate-600">{k}:</span>{" "}
                        {typeof v === "object" ? JSON.stringify(v) : String(v)}
                      </span>
                    ))}
                </div>
              </div>
            )}
          {/* bounding_box */}
          {chunk.bounding_box && (
            <div className="flex items-center gap-2">
              <span className="text-slate-600 w-24 shrink-0">bbox</span>
              <span className="font-mono text-slate-400">
                ({chunk.bounding_box.x0?.toFixed(1)},{" "}
                {chunk.bounding_box.y0?.toFixed(1)}) → (
                {chunk.bounding_box.x1?.toFixed(1)},{" "}
                {chunk.bounding_box.y1?.toFixed(1)})
              </span>
            </div>
          )}
        </div>
      )}

      {/* ── Chunk content ── */}
      <div className="p-3">
        {chunk.chunk_type === "text" && (
          <div className="text-xs leading-relaxed">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={mdTextComponents}
            >
              {chunk.chunk_text}
            </ReactMarkdown>
          </div>
        )}

        {chunk.chunk_type === "table" && (
          <div className="text-xs">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={mdTableComponents}
            >
              {chunk.chunk_text}
            </ReactMarkdown>
          </div>
        )}

        {(chunk.chunk_type === "multimodal" || chunk.chunk_type === "full_page_image") && (
          <div className="space-y-2.5">
            {chunk.gcs_image_path && (
              <div className="space-y-1">
                <img
                  src={imageUrl}
                  alt={`Page ${pageNum} visual`}
                  className="max-h-72 w-full rounded border border-slate-600 object-contain bg-slate-950"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = "none";
                  }}
                />
                <a
                  href={imageUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
                >
                  Open full size ↗
                </a>
              </div>
            )}
            <div className="border-t border-slate-700/50 pt-2.5">
              <p className="text-xs text-slate-500 mb-1.5">
                {chunk.chunk_type === "full_page_image" ? "Gemini full-page description:" : "Gemini description:"}
              </p>
              <div className="text-xs leading-relaxed">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={mdTextComponents}
                >
                  {chunk.chunk_text}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── MethodComparisonView: PyMuPDF vs MarkItDown side-by-side ─────────────────
function MethodComparisonView({
  doc,
  onClose,
}: {
  doc: Doc;
  onClose: () => void;
}) {
  const [data, setData] = useState<MethodComparisonData | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"chunks" | "search">("chunks");
  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [pymupdfResults, setPymupdfResults] = useState<ComparisonSearchResult[]>([]);
  const [mkdResults, setMkdResults] = useState<ComparisonSearchResult[]>([]);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetch(`${RAG_FL}/comparison/${doc.doc_id}?limit=50`)
      .then((r) => r.json())
      .then((d) => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [doc.doc_id]);

  async function handleComparisonSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    setPymupdfResults([]);
    setMkdResults([]);
    try {
      const res = await fetch(`${RAG_FL}/comparison/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: searchQuery, doc_id: doc.doc_id, top_k: 5 }),
      });
      const d = await res.json();
      setPymupdfResults(d.pymupdf_results || []);
      setMkdResults(d.markitdown_results || []);
    } catch { /* ignore */ }
    finally { setSearching(false); }
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
        Loading comparison data…
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
        Failed to load comparison data.
      </div>
    );
  }

  const markitdownReady = data.markitdown.total_chunks > 0;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="px-3 py-2 border-b border-slate-700 bg-slate-800 flex items-center gap-3 shrink-0 flex-wrap">
        <button
          onClick={onClose}
          className="text-xs text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1"
        >
          ← Back
        </button>
        <span className="text-slate-700">|</span>
        <span className="text-xs text-violet-400 font-semibold uppercase tracking-widest">
          ⚖ Method Comparison
        </span>
        <span className="text-xs text-slate-400 truncate max-w-xs">{doc.filename}</span>
        <div className="ml-auto flex items-center gap-1.5">
          {(["chunks", "search"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                activeTab === tab
                  ? "bg-violet-700 text-white"
                  : "bg-slate-700 text-slate-400 hover:text-slate-200"
              }`}
            >
              {tab === "chunks" ? "Chunks" : "Search Test"}
            </button>
          ))}
        </div>
      </div>

      {/* Method Comparison Information Banner */}
      {!bannerDismissed && (
        <div className="shrink-0 mx-3 mt-2 mb-0 rounded border border-blue-800/60 bg-blue-950/30 px-3 py-2.5 text-xs">
          <div className="flex items-start gap-2">
            <span className="text-blue-400 shrink-0 text-sm">ℹ</span>
            <div className="flex-1 space-y-1.5 text-slate-400">
              <p>
                <span className="text-blue-300 font-semibold">Method A ({data?.method_a_label ?? getMethodALabel(doc.original_format)})</span>
                {" "}— Converts Office files to PDF, uses PyMuPDF element detection, and
                calls <span className="text-slate-300">Gemini Vision</span> to describe charts, diagrams, and embedded images.
                Captures complete content including visual elements.
              </p>
              <p>
                <span className="text-emerald-300 font-semibold">Method B (MarkItDown)</span>
                {" "}— Reads Office files directly. Excellent for text paragraphs and structured tables.
                <span className="text-yellow-400"> Cannot read or describe visual content</span> (charts, diagrams, embedded images) —
                this is a library limitation, not a bug.
              </p>
              <p className="text-slate-500">
                For documents with charts or rich visuals, Method A will produce more complete chunks.
                For text-heavy or simple spreadsheets, both methods perform similarly.
              </p>
            </div>
            <button
              onClick={() => setBannerDismissed(true)}
              className="text-slate-600 hover:text-slate-400 transition-colors shrink-0 text-sm leading-none"
              title="Dismiss"
            >
              ×
            </button>
          </div>
        </div>
      )}

      {/* Stats bar — clean two-column Method A / Method B layout */}
      <div className="flex shrink-0 border-b border-slate-700 bg-slate-800/60 mt-2">
        {/* Method A */}
        <div className="flex-1 px-4 py-3 border-r border-slate-700">
          <div className="flex items-baseline gap-2 mb-1.5">
            <span className="text-xs text-slate-500 uppercase tracking-wider font-medium">Method A</span>
            <span className="text-sm font-bold text-blue-400">
              {data.method_a_label ?? getMethodALabel(data.original_format)}
            </span>
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-slate-500">
            <span className="text-slate-300 font-mono">{data.pymupdf.total_chunks} chunks</span>
            {Object.entries(data.pymupdf.type_breakdown).map(([t, n]) => (
              <span key={t} className={`px-1.5 py-0.5 rounded ${pageTypeCls(t)}`}>
                {t}: {n}
              </span>
            ))}
          </div>
        </div>
        {/* Method B */}
        <div className="flex-1 px-4 py-3">
          <div className="flex items-baseline gap-2 mb-1.5">
            <span className="text-xs text-slate-500 uppercase tracking-wider font-medium">Method B</span>
            <span className="text-sm font-bold text-emerald-400">
              MarkItDown — {data.method_b_label ?? getMethodBLabel(data.original_format)}
            </span>
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-slate-500">
            {markitdownReady ? (
              <>
                <span className="text-slate-300 font-mono">{data.markitdown.total_chunks} chunks</span>
                {Object.entries(data.markitdown.type_breakdown).map(([t, n]) => (
                  <span key={t} className={`px-1.5 py-0.5 rounded ${pageTypeCls(t)}`}>
                    {t}: {n}
                  </span>
                ))}
              </>
            ) : (
              <span className="text-yellow-500">Not processed yet — pipeline still running or failed</span>
            )}
          </div>
        </div>
      </div>

      {/* Chunks tab */}
      {activeTab === "chunks" && (
        <div className="flex-1 overflow-hidden flex">
          {/* PyMuPDF chunks */}
          <div className="flex-1 overflow-y-auto p-3 space-y-2 border-r border-slate-700">
            {data.pymupdf.chunks.length === 0 ? (
              <p className="text-xs text-slate-600 text-center mt-8">No chunks</p>
            ) : (
              data.pymupdf.chunks.map((c) => (
                <ComparisonChunkCard key={c.chunk_id} chunk={c} docId={doc.doc_id} accentColor="blue" />
              ))
            )}
            {data.pymupdf.total_chunks > data.pymupdf.chunks_shown && (
              <p className="text-xs text-slate-600 text-center py-2">
                … {data.pymupdf.total_chunks - data.pymupdf.chunks_shown} more chunks not shown
              </p>
            )}
          </div>
          {/* MarkItDown chunks */}
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {!markitdownReady ? (
              <div className="text-center mt-8 space-y-2">
                <p className="text-xs text-yellow-500">MarkItDown pipeline not yet run</p>
                <p className="text-xs text-slate-600">Re-upload the file or trigger /process to generate MarkItDown chunks</p>
              </div>
            ) : data.markitdown.chunks.length === 0 ? (
              <p className="text-xs text-slate-600 text-center mt-8">No chunks extracted</p>
            ) : (
              data.markitdown.chunks.map((c) => (
                <ComparisonChunkCard key={c.chunk_id} chunk={c} docId={doc.doc_id} accentColor="emerald" />
              ))
            )}
            {data.markitdown.total_chunks > data.markitdown.chunks_shown && (
              <p className="text-xs text-slate-600 text-center py-2">
                … {data.markitdown.total_chunks - data.markitdown.chunks_shown} more chunks not shown
              </p>
            )}
          </div>
        </div>
      )}

      {/* Search test tab */}
      {activeTab === "search" && (
        <div className="flex-1 overflow-hidden flex flex-col">
          {/* Search input */}
          <form onSubmit={handleComparisonSearch} className="flex gap-2 px-4 py-3 border-b border-slate-700 shrink-0">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Enter search query to test both methods…"
              className="flex-1 bg-slate-900 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-violet-500"
            />
            <button
              type="submit"
              disabled={searching || !searchQuery.trim()}
              className="px-4 py-1.5 text-sm bg-violet-700 hover:bg-violet-600 disabled:opacity-40 rounded text-white font-medium transition-colors"
            >
              {searching ? "…" : "Search Both"}
            </button>
          </form>

          {/* Results side by side */}
          <div className="flex-1 overflow-hidden flex">
            <div className="flex-1 overflow-y-auto p-3 space-y-2 border-r border-slate-700">
              <p className="text-xs text-blue-400 font-semibold mb-2">PyMuPDF Results</p>
              {pymupdfResults.length === 0 && !searching && (
                <p className="text-xs text-slate-600 text-center mt-4">Search to see results</p>
              )}
              {pymupdfResults.map((r) => (
                <SearchResultCard key={r.chunk_id} result={r} accentColor="blue" />
              ))}
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              <p className="text-xs text-emerald-400 font-semibold mb-2">MarkItDown Results</p>
              {mkdResults.length === 0 && !searching && (
                <p className="text-xs text-slate-600 text-center mt-4">Search to see results</p>
              )}
              {mkdResults.map((r) => (
                <SearchResultCard key={r.chunk_id} result={r} accentColor="emerald" />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── ComparisonChunkCard — full-fidelity card matching ChunkCard quality ───────
function ComparisonChunkCard({
  chunk,
  docId,
  accentColor,
}: {
  chunk: ComparisonChunk;
  docId: string;
  accentColor: "blue" | "emerald";
}) {
  const [expanded, setExpanded] = useState(false);
  const [metaOpen, setMetaOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const accentBorder = accentColor === "blue" ? "border-blue-800/40" : "border-emerald-800/40";
  const headerBg    = accentColor === "blue" ? "bg-blue-950/30"  : "bg-emerald-950/30";
  const dimColor    = accentColor === "blue" ? "text-blue-500"   : "text-emerald-500";

  const imageUrl = gcsImageUrl(chunk.gcs_image_path, docId, chunk.page_number);
  const showVisualBadge = chunk.chunk_type === "multimodal" && isVisualContent(chunk.chunk_text);

  function copyId() {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(chunk.chunk_id).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      });
    }
  }

  return (
    <div className={`border ${accentBorder} rounded overflow-hidden`}>
      {/* ── Header row: type badge + title + dims ── */}
      <div className={`flex flex-wrap items-center gap-1.5 px-3 py-2 ${headerBg} border-b border-slate-700/40`}>
        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${pageTypeCls(chunk.chunk_type)}`}>
          {chunkIcon(chunk.chunk_type)} {chunk.chunk_type}
        </span>
        {showVisualBadge && (
          <span className="px-1.5 py-0.5 rounded text-xs bg-violet-900/50 text-violet-300">
            📊 Visual
          </span>
        )}
        <span className="text-xs text-slate-500">
          {chunk.section_title
            ? <span className="text-slate-400 italic truncate max-w-[130px]" title={chunk.section_title}>
                {chunk.section_title}
              </span>
            : <span>pg {chunk.page_number}</span>}
        </span>
        {chunk.embedding_dims != null && (
          <span className={`ml-auto shrink-0 font-mono text-xs ${chunk.embedding_dims === 768 ? dimColor : "text-yellow-500"}`}>
            {chunk.embedding_dims === 768 ? "768-dim ✓" : `${chunk.embedding_dims}-dim`}
          </span>
        )}
      </div>

      {/* ── Sub-header: chunk ID + expand toggle ── */}
      <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-800/40 border-b border-slate-700/40">
        <span className="text-xs text-slate-600 shrink-0">ID</span>
        <button onClick={copyId} title="Copy chunk ID"
          className="font-mono text-xs text-slate-500 hover:text-slate-300 transition-colors truncate">
          {chunk.chunk_id.slice(0, 14)}…
        </button>
        {copied && <span className="text-xs text-green-500 shrink-0">copied!</span>}
        <button
          onClick={() => setExpanded(!expanded)}
          className="ml-auto text-xs text-slate-500 hover:text-slate-300 transition-colors shrink-0"
        >
          {expanded ? "▲ Collapse" : "▼ Expand"}
        </button>
      </div>

      {/* ── Expanded content ── */}
      {expanded && (
        <>
          {/* Metadata toggle */}
          <div className="flex items-center px-3 py-1.5 bg-slate-800/30 border-b border-slate-700/30">
            <span className="text-xs text-slate-600 font-mono">
              pg {chunk.page_number} · chunk {chunk.chunk_index}
            </span>
            <button
              onClick={() => setMetaOpen(!metaOpen)}
              className="ml-auto text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              {metaOpen ? "▲ Hide metadata" : "▼ Show metadata"}
            </button>
          </div>

          {/* Metadata panel */}
          {metaOpen && (
            <div className="px-3 py-2.5 bg-slate-950/60 border-b border-slate-700/40 space-y-1.5 text-xs">
              {/* chunk_id */}
              <div className="flex items-start gap-2">
                <span className="text-slate-600 w-24 shrink-0">chunk_id</span>
                <span className="font-mono text-slate-400 break-all">{chunk.chunk_id}</span>
              </div>
              {/* page */}
              <div className="flex items-center gap-2">
                <span className="text-slate-600 w-24 shrink-0">page</span>
                <span className="text-slate-400">Page {chunk.page_number}</span>
              </div>
              {/* section_title */}
              {chunk.section_title && (
                <div className="flex items-start gap-2">
                  <span className="text-slate-600 w-24 shrink-0">section</span>
                  <span className="text-slate-400">{chunk.section_title}</span>
                </div>
              )}
              {/* processing_method */}
              <div className="flex items-center gap-2">
                <span className="text-slate-600 w-24 shrink-0">method</span>
                <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                  (chunk.processing_method === "markitdown")
                    ? "bg-emerald-900/40 text-emerald-300"
                    : "bg-blue-900/40 text-blue-300"
                }`}>
                  {chunk.processing_method || "pymupdf"}
                </span>
              </div>
              {/* format_provenance */}
              {chunk.format_provenance && Object.keys(chunk.format_provenance).length > 0 && (
                <div className="flex items-start gap-2">
                  <span className="text-slate-600 w-24 shrink-0">provenance</span>
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(chunk.format_provenance)
                      .filter(([k]) => k !== "rows")
                      .map(([k, v]) => (
                        <span key={k} className="bg-slate-800 border border-slate-700 px-1.5 py-0.5 rounded text-slate-400">
                          <span className="text-slate-600">{k}:</span>{" "}
                          {typeof v === "object" ? JSON.stringify(v) : String(v)}
                        </span>
                      ))}
                  </div>
                </div>
              )}
              {/* gcs_image_path */}
              {chunk.gcs_image_path && (
                <div className="flex items-start gap-2">
                  <span className="text-slate-600 w-24 shrink-0">gcs_image</span>
                  <span className="font-mono text-slate-500 break-all text-xs">{chunk.gcs_image_path}</span>
                </div>
              )}
              {/* bounding_box */}
              {chunk.bounding_box && (
                <div className="flex items-center gap-2">
                  <span className="text-slate-600 w-24 shrink-0">bbox</span>
                  <span className="font-mono text-slate-400">
                    ({chunk.bounding_box.x0?.toFixed(1)}, {chunk.bounding_box.y0?.toFixed(1)}) →
                    ({chunk.bounding_box.x1?.toFixed(1)}, {chunk.bounding_box.y1?.toFixed(1)})
                  </span>
                </div>
              )}
            </div>
          )}

          {/* ── Chunk content — same rendering as ChunkCard ── */}
          <div className="p-3">
            {/* Multimodal or full_page_image: show image + Gemini description */}
            {(chunk.chunk_type === "multimodal" || chunk.chunk_type === "full_page_image") && (
              <div className="space-y-2.5">
                {chunk.gcs_image_path && (
                  <div className="space-y-1">
                    <img
                      src={imageUrl}
                      alt={`Page ${chunk.page_number} visual`}
                      className="max-h-64 w-full rounded border border-slate-600 object-contain bg-slate-950"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                    />
                    <a href={imageUrl} target="_blank" rel="noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300 transition-colors">
                      Open full size ↗
                    </a>
                  </div>
                )}
                <div className={chunk.gcs_image_path ? "border-t border-slate-700/50 pt-2.5" : ""}>
                  {chunk.gcs_image_path && (
                    <p className="text-xs text-slate-500 mb-1.5">
                      {chunk.chunk_type === "full_page_image" ? "Gemini full-page description:" : "Gemini description:"}
                    </p>
                  )}
                  <div className="text-xs leading-relaxed max-h-48 overflow-y-auto">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdTextComponents}>
                      {chunk.chunk_text}
                    </ReactMarkdown>
                  </div>
                </div>
              </div>
            )}

            {/* Table */}
            {chunk.chunk_type === "table" && (
              <div className="text-xs max-h-56 overflow-auto">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdTableComponents}>
                  {chunk.chunk_text}
                </ReactMarkdown>
              </div>
            )}

            {/* Text */}
            {(chunk.chunk_type === "text" || !["multimodal","full_page_image","table"].includes(chunk.chunk_type)) && (
              <div className="text-xs leading-relaxed max-h-48 overflow-y-auto">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdTextComponents}>
                  {chunk.chunk_text.slice(0, 1500) + (chunk.chunk_text.length > 1500 ? "\n\n…" : "")}
                </ReactMarkdown>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ── SearchResultCard — for method comparison search results ───────────────────
function SearchResultCard({
  result,
  accentColor,
}: {
  result: ComparisonSearchResult;
  accentColor: "blue" | "emerald";
}) {
  const scoreColor = accentColor === "blue" ? "bg-blue-500" : "bg-emerald-500";
  const scoreText = accentColor === "blue" ? "text-blue-400" : "text-emerald-400";

  return (
    <div className="bg-slate-900/60 rounded border border-slate-700 p-2.5 space-y-2">
      <div className="flex items-center gap-2">
        <div className="flex-1 bg-slate-700 rounded-full h-1.5">
          <div
            className={`${scoreColor} h-1.5 rounded-full`}
            style={{ width: `${Math.round(result.score * 100)}%` }}
          />
        </div>
        <span className={`text-xs font-mono ${scoreText} shrink-0 w-8 text-right`}>
          {(result.score * 100).toFixed(0)}%
        </span>
      </div>
      <div className="flex items-center gap-1.5 text-xs">
        <span className="bg-slate-700 px-1.5 py-0.5 rounded text-slate-300">
          pg {result.page_number}
        </span>
        <span className={`px-1.5 py-0.5 rounded ${pageTypeCls(result.chunk_type)}`}>
          {chunkIcon(result.chunk_type)} {result.chunk_type}
        </span>
      </div>
      <p className="text-xs text-slate-400 leading-relaxed line-clamp-3">
        {result.chunk_text}
      </p>
    </div>
  );
}

// ── ComparisonView component ──────────────────────────────────────────────────
function ComparisonView({
  group,
  onClose,
}: {
  group: Doc[];
  onClose: () => void;
}) {
  const [pageNum, setPageNum] = useState(1);
  const [chunksByDoc, setChunksByDoc] = useState<Record<string, Chunk[]>>({});
  const [loading, setLoading] = useState(false);

  const maxPages = Math.max(...group.map((d) => d.total_pages));

  useEffect(() => {
    setLoading(true);
    Promise.all(
      group.map((doc) =>
        fetch(`${RAG_FL}/document/${doc.doc_id}/chunks/${pageNum}`)
          .then((r) => (r.ok ? r.json() : { chunks: [] }))
          .then((data) => ({
            docId: doc.doc_id,
            chunks: (data.chunks || []) as Chunk[],
          }))
          .catch(() => ({ docId: doc.doc_id, chunks: [] as Chunk[] }))
      )
    ).then((results) => {
      const map: Record<string, Chunk[]> = {};
      results.forEach(({ docId, chunks }) => {
        map[docId] = chunks;
      });
      setChunksByDoc(map);
      setLoading(false);
    });
  }, [pageNum, group]);

  function formatBadgeCls(fmt: string): string {
    const colors: Record<string, string> = {
      pdf: "bg-red-900/40 text-red-300 border-red-800/50",
      xlsx: "bg-emerald-900/40 text-emerald-300 border-emerald-800/50",
      xls: "bg-emerald-900/40 text-emerald-300 border-emerald-800/50",
    };
    return (
      colors[fmt.toLowerCase()] ?? "bg-slate-700 text-slate-300 border-slate-600"
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Comparison header */}
      <div className="px-3 py-2 border-b border-slate-700 bg-slate-800 flex items-center gap-3 shrink-0">
        <button
          onClick={onClose}
          className="text-xs text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1"
        >
          ← Back to explorer
        </button>
        <span className="text-slate-700">|</span>
        <span className="text-xs text-slate-500 uppercase tracking-widest">
          ⊞ Comparison — {group.length} files
        </span>
        {maxPages > 1 && (
          <div className="ml-auto flex items-center gap-1.5">
            <span className="text-xs text-slate-500">Page:</span>
            <button
              disabled={pageNum <= 1}
              onClick={() => setPageNum((p) => p - 1)}
              className="w-6 h-6 flex items-center justify-center rounded bg-slate-700 text-slate-300 disabled:opacity-40 hover:bg-slate-600 transition-colors text-sm"
            >
              ‹
            </button>
            <span className="text-xs font-mono text-slate-300 w-5 text-center">
              {pageNum}
            </span>
            <button
              disabled={pageNum >= maxPages}
              onClick={() => setPageNum((p) => p + 1)}
              className="w-6 h-6 flex items-center justify-center rounded bg-slate-700 text-slate-300 disabled:opacity-40 hover:bg-slate-600 transition-colors text-sm"
            >
              ›
            </button>
          </div>
        )}
      </div>

      {/* Columns */}
      <div className="flex-1 overflow-auto">
        <div className="flex h-full">
          {group.map((doc) => {
            const chunks = chunksByDoc[doc.doc_id] || [];
            const hasVision = chunks.some((c) => c.chunk_type === "multimodal");
            const chunkTypes = [...new Set(chunks.map((c) => c.chunk_type))];

            return (
              <div
                key={doc.doc_id}
                className="w-80 min-w-[18rem] shrink-0 border-r border-slate-700 flex flex-col"
              >
                {/* Column header */}
                <div className="p-3 border-b border-slate-700 bg-slate-800/50 space-y-1.5 shrink-0">
                  <div className="flex items-start gap-1.5">
                    <span
                      className={`px-1.5 py-0.5 rounded text-xs border shrink-0 ${formatBadgeCls(doc.original_format)}`}
                    >
                      {doc.original_format.toUpperCase()}
                    </span>
                    <span
                      className="text-xs text-slate-200 leading-snug break-all"
                      title={doc.filename}
                    >
                      {doc.filename}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-500">
                    <span>{doc.total_pages}pg</span>
                    <span>·</span>
                    <span>{doc.chunk_count} chunks total</span>
                  </div>
                  {/* Fidelity badge */}
                  <div>
                    {hasVision ? (
                      <span className="inline-block px-1.5 py-0.5 rounded text-xs bg-purple-900/40 text-purple-300 border border-purple-800/50">
                        ▣ Vision description
                      </span>
                    ) : (
                      <span className="inline-block px-1.5 py-0.5 rounded text-xs bg-green-900/40 text-green-300 border border-green-800/50">
                        ≡ Full fidelity
                      </span>
                    )}
                    {chunkTypes.length > 0 && (
                      <span className="ml-1.5 text-xs text-slate-600">
                        {chunkTypes.join(", ")}
                      </span>
                    )}
                  </div>
                </div>

                {/* Column chunks */}
                <div className="flex-1 overflow-y-auto p-2.5 space-y-2.5">
                  {loading ? (
                    <p className="text-xs text-slate-500 py-6 text-center">
                      Loading…
                    </p>
                  ) : chunks.length === 0 ? (
                    <p className="text-xs text-slate-500 py-6 text-center">
                      No chunks on page {pageNum}
                    </p>
                  ) : (
                    chunks.map((chunk) => (
                      <ChunkCard
                        key={chunk.chunk_id}
                        chunk={chunk}
                        totalOnPage={chunks.length}
                        docId={doc.doc_id}
                        pageNum={pageNum}
                      />
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function Page() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [selectedDoc, setSelectedDoc] = useState<Doc | null>(null);
  const [pages, setPages] = useState<PageProfile[]>([]);
  const [expandedPage, setExpandedPage] = useState<number | null>(null);
  const [pageChunks, setPageChunks] = useState<Record<number, Chunk[]>>({});
  const [loadingPage, setLoadingPage] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState("");
  const [forceMixedMode, setForceMixedMode] = useState("—");
  const [compareGroup, setCompareGroup] = useState<Doc[] | null>(null);
  const [methodCompareDoc, setMethodCompareDoc] = useState<Doc | null>(null);
  const [comparisonDocStats, setComparisonDocStats] = useState<Record<string, { pymupdf: number; markitdown: number }>>({});
  const [leftSidebarOpen, setLeftSidebarOpen] = useState(true);
  const [rightSidebarOpen, setRightSidebarOpen] = useState(true);

  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    fetchDocs();
    fetchConfig();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // After comparison stats load: if user is in page explorer for an Office file
  // that now has both methods ready, auto-redirect to the comparison view.
  useEffect(() => {
    if (selectedDoc && Object.keys(comparisonDocStats).length > 0) {
      if (shouldAutoGoToMethodComparison(selectedDoc, comparisonDocStats)) {
        setMethodCompareDoc(selectedDoc);
        setSelectedDoc(null);
        setExpandedPage(null);
        setPageChunks({});
        setLeftSidebarOpen(false);
        setRightSidebarOpen(false);
      }
    }
  }, [comparisonDocStats]);

  async function fetchDocs() {
    setDocsLoading(true);
    try {
      // Load docs and comparison stats in parallel — avoids the timing race where
      // user clicks a file before stats are available and lands in page explorer instead.
      const [docsRes, cmpRes] = await Promise.all([
        fetch(`${RAG_FL}/documents?limit=100`),
        fetch(`${RAG_FL}/comparison/documents`).catch(() => null),
      ]);
      const data = await docsRes.json();
      setDocs((data.documents || []).filter((d: Doc) => d.status === "EMBEDDED"));
      if (cmpRes?.ok) {
        const cmpData = await cmpRes.json();
        const stats: Record<string, { pymupdf: number; markitdown: number }> = {};
        for (const d of (cmpData.documents || [])) {
          stats[d.doc_id] = { pymupdf: d.pymupdf_chunks, markitdown: d.markitdown_chunks };
        }
        setComparisonDocStats(stats);
      }
    } catch {
      /* network error */
    } finally {
      setDocsLoading(false);
    }
  }

  async function fetchConfig() {
    try {
      const res = await fetch(`${RAG_FL}/config`);
      const data = await res.json();
      setForceMixedMode(data.force_mixed_mode ?? "false");
    } catch {
      setForceMixedMode("unknown");
    }
  }

  async function handleSelectDoc(doc: Doc) {
    setCompareGroup(null);
    setExpandedPage(null);
    setPageChunks({});
    setSearchResults([]);
    setSearchQuery("");

    // Office files with both methods → go directly to method comparison view
    if (shouldAutoGoToMethodComparison(doc, comparisonDocStats)) {
      setMethodCompareDoc(doc);
      setSelectedDoc(null);
      // Auto-hide sidebars to give full width to comparison view
      setLeftSidebarOpen(false);
      setRightSidebarOpen(false);
      return;
    }

    // Restore sidebars for page explorer view
    setLeftSidebarOpen(true);
    setRightSidebarOpen(true);
    setMethodCompareDoc(null);
    setSelectedDoc(doc);
    try {
      const res = await fetch(`${RAG_FL}/document/${doc.doc_id}/pages`);
      const data = await res.json();
      setPages(data.pages || []);
    } catch {
      setPages([]);
    }
  }

  async function handlePageClick(pageNum: number) {
    if (expandedPage === pageNum) {
      setExpandedPage(null);
      return;
    }
    setExpandedPage(pageNum);
    if (pageChunks[pageNum]) return;
    setLoadingPage(pageNum);
    try {
      const res = await fetch(
        `${RAG_FL}/document/${selectedDoc!.doc_id}/chunks/${pageNum}`
      );
      const data = await res.json();
      setPageChunks((prev) => ({ ...prev, [pageNum]: data.chunks || [] }));
    } catch {
      setPageChunks((prev) => ({ ...prev, [pageNum]: [] }));
    } finally {
      setLoadingPage(null);
    }
  }

  function startPolling(docId: string, filename: string) {
    if (pollRef.current) clearInterval(pollRef.current);
    let polls = 0;
    const MAX_POLLS = 60; // 3 min

    pollRef.current = setInterval(async () => {
      polls++;
      try {
        const res = await fetch(`${INGEST}/documents/${docId}`);
        if (!res.ok) return;
        const doc = await res.json();
        if (doc.status === "EMBEDDED") {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          const allRes = await fetch(`${RAG_FL}/documents?limit=100`);
          const allData = await allRes.json();
          const embedded = (allData.documents || []).find(
            (d: Doc) => d.doc_id === docId
          );
          const chunkCount = embedded?.chunk_count ?? "?";
          setUploadMsg(`Embedding complete! ${chunkCount} chunks created.`);
          await fetchDocs();
          setTimeout(() => setUploadMsg(""), 5000);
        } else if (polls >= MAX_POLLS) {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setUploadMsg("Processing timeout — check logs");
          setTimeout(() => setUploadMsg(""), 5000);
        }
      } catch {
        /* keep polling */
      }
    }, 3000);
  }

  async function handleUpload(file: File) {
    setUploading(true);
    setUploadMsg("");
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${INGEST}/ingest`, { method: "POST", body: form });
      if (!res.ok) {
        setUploadMsg("Upload failed");
        return;
      }
      const data = await res.json();
      if (data.status === "duplicate") {
        setUploadMsg("Duplicate — already ingested.");
        setTimeout(() => setUploadMsg(""), 3000);
      } else if (data.doc_id) {
        setUploadMsg("Processing in background…");
        startPolling(data.doc_id, file.name);
      }
    } catch {
      setUploadMsg("Upload failed");
      setTimeout(() => setUploadMsg(""), 5000);
    } finally {
      setUploading(false);
    }
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedDoc || !searchQuery.trim()) return;
    setSearching(true);
    setSearchResults([]);
    try {
      const res = await fetch(
        `${RAG_FL}/search/within/${selectedDoc.doc_id}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: searchQuery, top_k: 5 }),
        }
      );
      const data = await res.json();
      setSearchResults(data.results || []);
    } catch {
      /* search failed */
    } finally {
      setSearching(false);
    }
  }

  function scrollToPage(pageNum: number) {
    if (expandedPage !== pageNum) handlePageClick(pageNum);
    setTimeout(() => {
      pageRefs.current[pageNum]?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 150);
  }

  // Detect comparison groups from the loaded (EMBEDDED) docs
  const comparisonGroups = detectComparisonGroups(docs);

  // Build the left-panel doc list, inserting [Compare] buttons after each group's last member
  function renderDocList(): React.ReactNode[] {
    const rendered: React.ReactNode[] = [];
    const shownGroupButtons = new Set<string>();

    docs.forEach((doc, idx) => {
      const cmpStats = comparisonDocStats[doc.doc_id];
      const isBaseline = BASELINE_FILENAMES.has(doc.filename);
      const isNoComparison = !OFFICE_FORMATS.has(doc.original_format);
      const hasBothMethods = !isBaseline && !isNoComparison &&
        cmpStats && cmpStats.pymupdf > 0 && cmpStats.markitdown > 0;
      const isMethodCompare = methodCompareDoc?.doc_id === doc.doc_id;

      rendered.push(
        <div key={doc.doc_id}>
          <button
            onClick={() => handleSelectDoc(doc)}
            className={`w-full text-left px-3 py-2.5 border-b border-slate-700/50 hover:bg-slate-700/40 transition-colors ${
              (selectedDoc?.doc_id === doc.doc_id || isMethodCompare)
                ? "bg-indigo-900/30 border-l-2 border-l-indigo-500"
                : ""
            }`}
          >
            <div className="flex items-start gap-1.5 justify-between">
              <span className="text-sm text-slate-200 leading-snug truncate">
                {doc.filename}
              </span>
              <span
                className={`shrink-0 px-1.5 py-0.5 rounded text-xs ${statusCls(doc.status)}`}
              >
                {doc.status}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 mt-1 text-xs text-slate-500">
              <span className="font-mono bg-slate-700 px-1 rounded text-slate-300">
                {doc.original_format?.toUpperCase()}
              </span>
              <span>{doc.total_pages}pg</span>
              <span>{doc.chunk_count} chunks</span>
              {doc.report_period && (
                <span className="text-cyan-600">{doc.report_period}</span>
              )}
              {/* Badge: direct comparison or page explorer */}
              {hasBothMethods && (
                <span className="text-violet-500 text-xs">⚖ Compare</span>
              )}
            </div>
          </button>
        </div>
      );

      // After this doc, check if we should show a Compare button for its group
      const base = normalizeBaseName(doc.filename);
      const group = comparisonGroups.get(base);
      if (group && !shownGroupButtons.has(base)) {
        // Find the index of the last group member in the docs array
        const lastGroupIdx = Math.max(
          ...group.map((d) => docs.findIndex((dd) => dd.doc_id === d.doc_id))
        );
        if (idx === lastGroupIdx) {
          shownGroupButtons.add(base);
          rendered.push(
            <div
              key={`compare-${base}`}
              className="px-3 py-1.5 border-b border-indigo-900/30 bg-indigo-950/20"
            >
              <button
                onClick={() => {
                  setCompareGroup(group);
                  setSelectedDoc(null);
                }}
                className="w-full text-xs text-indigo-400 hover:text-indigo-300 transition-colors flex items-center gap-1.5 py-0.5"
              >
                <span className="text-sm">⊞</span>
                <span>
                  Compare {group.length} files ({base})
                </span>
              </button>
            </div>
          );
        }
      }
    });

    return rendered;
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* ── TOP BAR ──────────────────────────────────────────────────────────── */}
      <header className="flex items-center justify-between px-4 py-2 bg-slate-800 border-b border-slate-700 shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <span className="font-bold text-indigo-400 text-base tracking-tight shrink-0">
            RAG-FL Observability
          </span>
          {selectedDoc && (
            <>
              <span className="text-slate-600 shrink-0">/</span>
              <span className="text-slate-300 text-sm truncate">
                {selectedDoc.filename}
              </span>
            </>
          )}
          {compareGroup && (
            <>
              <span className="text-slate-600 shrink-0">/</span>
              <span className="text-slate-300 text-sm">Format Comparison</span>
            </>
          )}
          {methodCompareDoc && (
            <>
              <span className="text-slate-600 shrink-0">/</span>
              <span className="text-violet-400 text-sm">
                A: {getMethodALabel(methodCompareDoc.original_format)} · B: MarkItDown
              </span>
            </>
          )}
        </div>
        <div className="flex items-center gap-4 text-xs shrink-0">
          <span className="text-slate-400">
            FORCE_MIXED_MODE{" "}
            <span
              className={
                forceMixedMode === "true"
                  ? "text-orange-400 font-mono font-bold"
                  : "text-green-400 font-mono"
              }
            >
              {forceMixedMode}
            </span>
          </span>
        </div>
      </header>

      {/* ── THREE PANELS ─────────────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0">
        {/* ── LEFT: File List ───────────────────────────────────────────────── */}
        {leftSidebarOpen && (
          <aside className="w-72 shrink-0 bg-slate-800 border-r border-slate-700 flex flex-col">
            {/* Upload controls */}
            <div className="p-3 border-b border-slate-700 space-y-2">
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                onChange={(e) =>
                  e.target.files?.[0] && handleUpload(e.target.files[0])
                }
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="w-full py-1.5 text-sm bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded text-white font-medium transition-colors"
              >
                {uploading ? "Uploading…" : "+ Upload File"}
              </button>
              {uploadMsg && (
                <p className="text-xs text-slate-400 truncate">{uploadMsg}</p>
              )}
            </div>

            {/* Document rows */}
            <div className="flex-1 overflow-y-auto">
              {docsLoading ? (
                <p className="p-4 text-sm text-slate-500">Loading…</p>
              ) : docs.length === 0 ? (
                <p className="p-4 text-sm text-slate-500">No documents found.</p>
              ) : (
                renderDocList()
              )}
            </div>

            <div className="px-3 py-1.5 text-xs text-slate-600 border-t border-slate-700">
              {docs.length} document{docs.length !== 1 ? "s" : ""}
            </div>
          </aside>
        )}

        {/* Left sidebar toggle button */}
        <button
          onClick={() => setLeftSidebarOpen((v) => !v)}
          title={leftSidebarOpen ? "Hide file list" : "Show file list"}
          className="shrink-0 w-4 flex items-center justify-center bg-slate-800 border-r border-slate-700 hover:bg-slate-700 transition-colors text-slate-500 hover:text-slate-300 text-xs"
        >
          {leftSidebarOpen ? "◀" : "▶"}
        </button>

        {/* ── CENTER: Page Explorer / Method Comparison / Format Comparison ──── */}
        <main className="flex-1 min-w-0 flex flex-col overflow-hidden bg-slate-900">
          {methodCompareDoc ? (
            <MethodComparisonView
              doc={methodCompareDoc}
              onClose={() => {
                setMethodCompareDoc(null);
                setLeftSidebarOpen(true);
                setRightSidebarOpen(true);
              }}
            />
          ) : compareGroup ? (
            <ComparisonView
              group={compareGroup}
              onClose={() => setCompareGroup(null)}
            />
          ) : !selectedDoc ? (
            <div className="flex-1 flex items-center justify-center text-slate-600">
              <p className="text-sm">Select a document to explore its pages</p>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto p-3 space-y-1.5">
              <div className="mb-2 text-xs text-slate-600 uppercase tracking-widest">
                Page Explorer — {pages.length} pages
              </div>

              {pages.map((pg) => {
                const isExpanded = expandedPage === pg.page_number;
                const chunks = pageChunks[pg.page_number] ?? [];
                const isLoading = loadingPage === pg.page_number;

                return (
                  <div
                    key={pg.page_number}
                    ref={(el) => {
                      pageRefs.current[pg.page_number] = el;
                    }}
                    className={`rounded border transition-all ${
                      isExpanded
                        ? "border-indigo-600 bg-slate-800"
                        : "border-slate-700/50 bg-slate-800/30 hover:border-slate-600"
                    }`}
                  >
                    {/* Page row header */}
                    <button
                      onClick={() => handlePageClick(pg.page_number)}
                      className="w-full flex items-center gap-3 px-3 py-2 text-left"
                    >
                      <span className="text-xs text-slate-500 w-12 shrink-0 font-mono">
                        pg {pg.page_number}
                      </span>
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-medium ${pageTypeCls(pg.page_type)}`}
                      >
                        {pg.page_type}
                      </span>
                      <span className="text-xs text-slate-500">
                        {pg.chunk_count} chunk
                        {pg.chunk_count !== 1 ? "s" : ""}
                      </span>
                      <span className="ml-auto text-xs text-slate-600">
                        {isExpanded ? "▲" : "▼"}
                      </span>
                    </button>

                    {/* Expanded chunk details */}
                    {isExpanded && (
                      <div className="border-t border-slate-700 px-3 pb-3">
                        {isLoading ? (
                          <p className="text-xs text-slate-500 py-3">
                            Loading chunks…
                          </p>
                        ) : chunks.length === 0 ? (
                          <p className="text-xs text-slate-500 py-3">
                            No chunks — page type &quot;{pg.page_type}&quot; produces no
                            embedding.
                          </p>
                        ) : (
                          <div className="space-y-3 pt-2">
                            {chunks.map((chunk) => (
                              <ChunkCard
                                key={chunk.chunk_id}
                                chunk={chunk}
                                totalOnPage={chunks.length}
                                docId={selectedDoc.doc_id}
                                pageNum={pg.page_number}
                              />
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </main>

        {/* ── RIGHT: Search ─────────────────────────────────────────────────── */}
        {/* Right sidebar toggle button */}
        <button
          onClick={() => setRightSidebarOpen((v) => !v)}
          title={rightSidebarOpen ? "Hide search panel" : "Show search panel"}
          className="shrink-0 w-4 flex items-center justify-center bg-slate-800 border-l border-slate-700 hover:bg-slate-700 transition-colors text-slate-500 hover:text-slate-300 text-xs"
        >
          {rightSidebarOpen ? "▶" : "◀"}
        </button>

        {rightSidebarOpen && (
        <aside className="w-80 shrink-0 bg-slate-800 border-l border-slate-700 flex flex-col">
          <div className="p-3 border-b border-slate-700">
            <p className="text-xs text-slate-500 uppercase tracking-widest mb-2">
              Search
            </p>
            <form onSubmit={handleSearch} className="space-y-2">
              <textarea
                rows={2}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={
                  selectedDoc
                    ? "Ask anything about this document…"
                    : "Select a document first"
                }
                disabled={!selectedDoc}
                className="w-full bg-slate-900 border border-slate-600 rounded px-2.5 py-1.5 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-indigo-500 resize-none disabled:opacity-40 transition-colors"
              />
              <button
                type="submit"
                disabled={!selectedDoc || searching || !searchQuery.trim()}
                className="w-full py-1.5 text-sm bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 rounded text-white font-medium transition-colors"
              >
                {searching ? "Searching…" : "Search"}
              </button>
            </form>
          </div>

          {/* Results */}
          <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
            {searchResults.length === 0 && !searching && (
              <p className="text-xs text-slate-600 text-center mt-8">
                {selectedDoc
                  ? "Results appear here"
                  : "Select a document to search"}
              </p>
            )}

            {searchResults.map((r) => (
              <button
                key={r.chunk_id}
                onClick={() => scrollToPage(r.page_number)}
                className="w-full text-left bg-slate-900/60 rounded border border-slate-700 hover:border-indigo-500 transition-colors p-2.5 space-y-2"
              >
                {/* Score bar */}
                <div className="flex items-center gap-2">
                  <div className="flex-1 bg-slate-700 rounded-full h-1.5">
                    <div
                      className="bg-indigo-500 h-1.5 rounded-full transition-all"
                      style={{ width: `${Math.round(r.score * 100)}%` }}
                    />
                  </div>
                  <span className="text-xs font-mono text-indigo-400 shrink-0 w-8 text-right">
                    {(r.score * 100).toFixed(0)}%
                  </span>
                </div>

                {/* Badges */}
                <div className="flex items-center gap-1.5 text-xs">
                  <span className="bg-slate-700 px-1.5 py-0.5 rounded text-slate-300">
                    pg {r.page_number}
                  </span>
                  <span
                    className={`px-1.5 py-0.5 rounded ${pageTypeCls(r.chunk_type)}`}
                  >
                    {chunkIcon(r.chunk_type)} {r.chunk_type}
                  </span>
                </div>

                {/* Snippet */}
                <p className="text-xs text-slate-400 leading-relaxed line-clamp-3">
                  {r.chunk_text}
                </p>

                {/* Citation */}
                <p className="text-xs text-indigo-400/70">
                  {selectedDoc?.filename} · Page {r.page_number}
                  {r.section_title ? ` · ${r.section_title}` : ""}
                </p>
              </button>
            ))}
          </div>
        </aside>
        )}
      </div>
    </div>
  );
}
