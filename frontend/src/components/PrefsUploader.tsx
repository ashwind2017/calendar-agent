"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { DrivePicker } from "@/components/DrivePicker";

type Props = {
  sessionId: string;
};

export function PrefsUploader({ sessionId }: Props) {
  const [text, setText] = useState("");
  const [source, setSource] = useState("preferences.md");
  const [busy, setBusy] = useState(false);
  const [sources, setSources] = useState<Record<string, number>>({});
  const [status, setStatus] = useState<string | null>(null);

  async function refresh() {
    try {
      const r = await api.ragList(sessionId);
      setSources(r.sources);
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  async function upload() {
    if (!text.trim()) return;
    setBusy(true);
    setStatus(null);
    try {
      const r = await api.uploadPrefsText(sessionId, source.trim() || "untitled", text);
      setStatus(`Indexed. Total chunks: ${r.entries}`);
      setText("");
      refresh();
    } catch (e: unknown) {
      setStatus(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function clearAll() {
    if (!confirm("Clear all indexed notes for this session?")) return;
    setBusy(true);
    await api.ragClear(sessionId);
    setSources({});
    setStatus("Cleared.");
    setBusy(false);
  }

  return (
    <div className="space-y-3">
      <div>
        <h2 className="font-semibold text-zinc-800 text-sm">Personal context (RAG)</h2>
        <p className="text-xs text-zinc-500 mt-1">
          Paste preferences, notes about people, project context. The agent retrieves relevant chunks when making scheduling decisions or generating prep briefs.
        </p>
      </div>

      <input
        value={source}
        onChange={(e) => setSource(e.target.value)}
        placeholder="Label (e.g., scheduling_preferences)"
        className="w-full border border-zinc-300 rounded px-2 py-1 text-xs"
      />

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={6}
        placeholder={"E.g.\n- I do my best deep work mornings 8-11am, protect this for solo work.\n- 1:1 with Sarah: she prefers Thursdays, last 1:1 had open items on the Q3 launch."}
        className="w-full border border-zinc-300 rounded px-2 py-1 text-xs font-mono"
      />

      <div className="flex gap-2">
        <button
          onClick={upload}
          disabled={busy || !text.trim()}
          className="px-3 py-1 bg-zinc-900 text-white rounded text-xs disabled:opacity-50"
        >
          {busy ? "..." : "Index"}
        </button>
        {Object.keys(sources).length > 0 && (
          <button
            onClick={clearAll}
            disabled={busy}
            className="px-3 py-1 border border-zinc-300 rounded text-xs"
          >
            Clear all
          </button>
        )}
      </div>

      {status && <div className="text-xs text-zinc-600">{status}</div>}

      {Object.keys(sources).length > 0 && (
        <div className="text-xs text-zinc-600 border-t border-zinc-200 pt-2">
          <div className="font-semibold mb-1">Indexed:</div>
          <ul className="space-y-1">
            {Object.entries(sources).map(([s, n]) => (
              <li key={s} className="truncate" title={s}>
                <span className="font-mono">{s}</span>{" "}
                <span className="text-zinc-400">({n} chunks)</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <DrivePicker sessionId={sessionId} onIndexed={refresh} />
    </div>
  );
}
