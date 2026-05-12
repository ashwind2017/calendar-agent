"use client";

import { useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type DriveFile = {
  id: string;
  name: string;
  mimeType: string;
  modifiedTime?: string;
  webViewLink?: string;
};

type Props = {
  sessionId: string;
  onIndexed?: () => void;
};

export function DrivePicker({ sessionId, onIndexed }: Props) {
  const [query, setQuery] = useState("");
  const [files, setFiles] = useState<DriveFile[]>([]);
  const [searching, setSearching] = useState(false);
  const [indexing, setIndexing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function search() {
    setSearching(true);
    setError(null);
    try {
      const url = new URL(`${API_BASE}/drive/search`);
      url.searchParams.set("session_id", sessionId);
      if (query) url.searchParams.set("q", query);
      const r = await fetch(url.toString());
      if (!r.ok) throw new Error(`Search failed: ${r.status}`);
      const data = await r.json();
      setFiles(data.files || []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSearching(false);
    }
  }

  async function indexFile(file: DriveFile) {
    setIndexing(file.id);
    setError(null);
    try {
      const url = new URL(`${API_BASE}/rag/index-drive-file`);
      url.searchParams.set("session_id", sessionId);
      url.searchParams.set("file_id", file.id);
      const r = await fetch(url.toString(), { method: "POST" });
      if (!r.ok) {
        const detail = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(detail.detail || r.statusText);
      }
      onIndexed?.();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIndexing(null);
    }
  }

  return (
    <div className="space-y-2 border-t border-zinc-200 pt-3 mt-3">
      <h3 className="font-semibold text-zinc-800 text-xs">Or index from Drive</h3>
      <div className="flex gap-1">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              search();
            }
          }}
          placeholder="Search Drive..."
          className="flex-1 border border-zinc-300 rounded px-2 py-1 text-xs"
        />
        <button
          onClick={search}
          disabled={searching}
          className="px-2 py-1 bg-zinc-200 text-zinc-800 rounded text-xs disabled:opacity-50"
        >
          {searching ? "..." : "Search"}
        </button>
      </div>
      {error && <div className="text-xs text-red-600">{error}</div>}
      {files.length > 0 && (
        <ul className="text-xs space-y-1 max-h-48 overflow-y-auto">
          {files.map((f) => (
            <li key={f.id} className="flex items-center justify-between gap-2 border border-zinc-200 rounded p-2">
              <span className="truncate" title={f.name}>
                {f.name}
              </span>
              <button
                onClick={() => indexFile(f)}
                disabled={indexing === f.id}
                className="px-2 py-0.5 bg-zinc-900 text-white rounded text-[10px] disabled:opacity-50 shrink-0"
              >
                {indexing === f.id ? "..." : "Index"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
