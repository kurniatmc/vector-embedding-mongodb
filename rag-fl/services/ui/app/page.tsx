"use client";

import React, { useState, useEffect, useRef } from "react";

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

// ── Styling helpers ───────────────────────────────────────────────────────────
function pageTypeCls(type: string): string {
  const m: Record<string, string> = {
    text: "bg-blue-700 text-blue-100",
    table: "bg-green-700 text-green-100",
    multimodal: "bg-purple-700 text-purple-100",
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
  return { text: "T", table: "≡", multimodal: "▣" }[type] ?? "?";
}

// ── Markdown table renderer ───────────────────────────────────────────────────
function MarkdownTable({ text }: { text: string }) {
  const lines = text
    .trim()
    .split("\n")
    .filter((l) => l.trim());

  if (lines.length < 2 || !lines[0].includes("|")) {
    return (
      <pre className="text-xs text-slate-300 whitespace-pre-wrap font-mono">
        {text}
      </pre>
    );
  }

  const parseRow = (line: string) =>
    line
      .split("|")
      .slice(1, -1)
      .map((c) => c.trim());

  const headers = parseRow(lines[0]);
  const rows = lines.slice(2).map(parseRow); // skip separator line

  return (
    <div className="overflow-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th
                key={i}
                className="border border-slate-600 px-2 py-1 bg-green-900/30 text-green-300 text-left whitespace-nowrap"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className="odd:bg-slate-800/40">
              {row.map((cell, ci) => (
                <td
                  key={ci}
                  className="border border-slate-600 px-2 py-1 text-slate-300 whitespace-nowrap"
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
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
  const [uploadedDocId, setUploadedDocId] = useState<string | null>(null);
  const [processing, setProcessing] = useState(false);
  const [processMsg, setProcessMsg] = useState("");
  const [forceMixedMode, setForceMixedMode] = useState("—");

  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    fetchDocs();
    fetchConfig();
  }, []);

  async function fetchDocs() {
    setDocsLoading(true);
    try {
      const res = await fetch(`${RAG_FL}/documents?limit=100`);
      const data = await res.json();
      setDocs(data.documents || []);
    } catch {
      /* network error — leave empty */
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
    setSelectedDoc(doc);
    setExpandedPage(null);
    setPageChunks({});
    setSearchResults([]);
    setSearchQuery("");
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
    if (pageChunks[pageNum]) return; // already cached
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

  async function handleUpload(file: File) {
    setUploading(true);
    setUploadedDocId(null);
    setProcessMsg("");
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${INGEST}/ingestion/ingest`, {
        method: "POST",
        body: form,
      });
      const data = await res.json();
      if (data.doc_id) {
        setUploadedDocId(data.doc_id);
        await fetchDocs();
      }
    } catch {
      setProcessMsg("Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleProcess(docId: string) {
    setProcessing(true);
    setProcessMsg("Processing…");
    try {
      const res = await fetch(`${RAG_FL}/process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_id: docId }),
      });
      const data = await res.json();
      setProcessMsg(data.message || data.status || "Done");
      await fetchDocs();
    } catch {
      setProcessMsg("Processing failed");
    } finally {
      setProcessing(false);
    }
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedDoc || !searchQuery.trim()) return;
    setSearching(true);
    setSearchResults([]);
    try {
      const res = await fetch(`${RAG_FL}/search/within/${selectedDoc.doc_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: searchQuery, top_k: 5 }),
      });
      const data = await res.json();
      setSearchResults(data.results || []);
    } catch {
      /* search failed */
    } finally {
      setSearching(false);
    }
  }

  function scrollToPage(pageNum: number) {
    // Expand the target page and fetch its chunks if needed
    if (expandedPage !== pageNum) {
      handlePageClick(pageNum);
    }
    setTimeout(() => {
      pageRefs.current[pageNum]?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 150);
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
            {uploadedDocId && (
              <button
                onClick={() => handleProcess(uploadedDocId)}
                disabled={processing}
                className="w-full py-1.5 text-sm bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 rounded text-white font-medium transition-colors"
              >
                {processing ? "Processing…" : "Process →"}
              </button>
            )}
            {processMsg && (
              <p className="text-xs text-slate-400 truncate">{processMsg}</p>
            )}
          </div>

          {/* Document rows */}
          <div className="flex-1 overflow-y-auto">
            {docsLoading ? (
              <p className="p-4 text-sm text-slate-500">Loading…</p>
            ) : docs.length === 0 ? (
              <p className="p-4 text-sm text-slate-500">No documents found.</p>
            ) : (
              docs.map((doc) => (
                <button
                  key={doc.doc_id}
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
                </button>
              ))
            )}
          </div>

          <div className="px-3 py-1.5 text-xs text-slate-600 border-t border-slate-700">
            {docs.length} document{docs.length !== 1 ? "s" : ""}
          </div>
        </aside>

        {/* ── CENTER: Page Explorer ─────────────────────────────────────────── */}
        <main className="flex-1 min-w-0 flex flex-col overflow-hidden bg-slate-900">
          {!selectedDoc ? (
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
                            No chunks — page type "{pg.page_type}" produces no
                            embedding.
                          </p>
                        ) : (
                          <div className="space-y-3 pt-2">
                            {chunks.map((chunk) => (
                              <div key={chunk.chunk_id} className="space-y-1.5">
                                {/* Chunk header */}
                                <div className="flex items-center gap-2 text-xs">
                                  <span
                                    className={`px-1.5 py-0.5 rounded ${pageTypeCls(chunk.chunk_type)}`}
                                  >
                                    {chunk.chunk_type}
                                  </span>
                                  {chunk.section_title && (
                                    <span className="text-slate-400 italic truncate">
                                      {chunk.section_title}
                                    </span>
                                  )}
                                  <span
                                    className={`ml-auto shrink-0 font-mono text-xs ${
                                      chunk.embedding_dims === 768
                                        ? "text-green-500"
                                        : "text-yellow-500"
                                    }`}
                                  >
                                    {chunk.embedding_dims === 768
                                      ? "768-dim ✓"
                                      : `${chunk.embedding_dims}-dim`}
                                  </span>
                                </div>

                                {/* Chunk body */}
                                {chunk.chunk_type === "text" && (
                                  <pre className="text-xs text-slate-300 whitespace-pre-wrap font-mono bg-slate-900 rounded p-2.5 max-h-56 overflow-y-auto leading-relaxed">
                                    {chunk.chunk_text}
                                  </pre>
                                )}

                                {chunk.chunk_type === "table" && (
                                  <div className="bg-slate-900 rounded p-2 max-h-56 overflow-auto">
                                    <MarkdownTable text={chunk.chunk_text} />
                                  </div>
                                )}

                                {chunk.chunk_type === "multimodal" && (
                                  <div className="space-y-2">
                                    {chunk.gcs_image_path && (
                                      <img
                                        src={`${RAG_FL}/image/${selectedDoc.doc_id}/${pg.page_number}`}
                                        alt={`Page ${pg.page_number}`}
                                        className="max-h-72 rounded border border-slate-600 object-contain bg-slate-950"
                                        onError={(e) => {
                                          (
                                            e.target as HTMLImageElement
                                          ).style.display = "none";
                                        }}
                                      />
                                    )}
                                    <div className="bg-slate-900 rounded p-2.5">
                                      <p className="text-xs text-slate-500 mb-1">
                                        Gemini description:
                                      </p>
                                      <p className="text-xs text-slate-300 leading-relaxed">
                                        {chunk.chunk_text}
                                      </p>
                                    </div>
                                  </div>
                                )}
                              </div>
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
                {selectedDoc ? "Results appear here" : "Select a document to search"}
              </p>
            )}

            {searchResults.map((r, i) => (
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
