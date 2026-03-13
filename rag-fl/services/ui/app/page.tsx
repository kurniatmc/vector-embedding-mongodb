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
  processing_info?: string;
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

// ── Processing info helper ────────────────────────────────────────────────────
function getProcessingInfo(format: string): string {
  if (["xlsx", "xls", "csv"].includes(format)) return "MarkItDown + Vision (charts)";
  if (["docx", "pptx"].includes(format)) return "Gotenberg → PDF → Vision";
  if (format === "pdf") return "PyMuPDF + Vision";
  if (["jpeg", "jpg", "png", "bmp", "tiff", "gif", "webp"].includes(format)) return "Vision";
  if (["yaml", "yml"].includes(format)) return "YAML parser";
  return "Standard pipeline";
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

// ── ComparisonView component (format comparison — multiple files same base name) ──
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

  async function fetchDocs() {
    setDocsLoading(true);
    try {
      const res = await fetch(`${RAG_FL}/documents?limit=100`);
      const data = await res.json();
      setDocs((data.documents || []).filter((d: Doc) => d.status === "EMBEDDED"));
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

    void filename; // suppress unused warning
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
      rendered.push(
        <div key={doc.doc_id}>
          <button
            onClick={() => handleSelectDoc(doc)}
            className={`w-full text-left px-3 py-2.5 border-b border-slate-700/50 hover:bg-slate-700/40 transition-colors ${
              selectedDoc?.doc_id === doc.doc_id
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
            </div>
            <div className="mt-0.5 text-xs text-slate-500">
              {doc.processing_info ?? getProcessingInfo(doc.original_format)}
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

        {/* ── CENTER: Page Explorer / Format Comparison ─────────────────────── */}
        <main className="flex-1 min-w-0 flex flex-col overflow-hidden bg-slate-900">
          {compareGroup ? (
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
      </div>
    </div>
  );
}
