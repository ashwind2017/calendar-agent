"use client";

import { useEffect, useState } from "react";
import { api, PrepBrief } from "@/lib/api";

type Props = {
  sessionId: string;
  eventId: string;
  onClose: () => void;
};

export function PrepBriefModal({ sessionId, eventId, onClose }: Props) {
  const [brief, setBrief] = useState<PrepBrief | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
     
    setLoading(true);
     
    setError(null);
    api
      .prepBrief(sessionId, eventId)
      .then((b) => {
        if (!cancelled) setBrief(b);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, eventId]);

  return (
    <div
      className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg max-w-2xl w-full max-h-[85vh] overflow-y-auto shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-zinc-200 p-4 flex items-center justify-between sticky top-0 bg-white">
          <h2 className="font-semibold text-zinc-900">Meeting prep brief</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-900 text-xl leading-none">
            &times;
          </button>
        </div>

        <div className="p-5">
          {loading && <div className="text-zinc-500 text-sm">Generating brief...</div>}
          {error && <div className="text-red-600 text-sm">Error: {error}</div>}
          {brief && (
            <>
              <div className="mb-4">
                <div className="font-medium text-zinc-900">{brief.meeting.summary}</div>
                <div className="text-xs text-zinc-500 mt-0.5">
                  {new Date(brief.meeting.start).toLocaleString()}
                  {" – "}
                  {new Date(brief.meeting.end).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}
                </div>
                <div className="text-xs text-zinc-600 mt-1">
                  {brief.data_sources.attendees_resolved} attendee(s){" · "}
                  {brief.data_sources.past_meetings_count} past meeting(s) considered{" · "}
                  {brief.data_sources.rag_chunks_used} note chunk(s) retrieved
                </div>
              </div>
              <div className="prose prose-sm prose-zinc max-w-none">
                {/* Render markdown lightly: split on blank lines, headers, lists */}
                <SimpleMarkdown text={brief.brief_markdown} />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function SimpleMarkdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const out: React.ReactNode[] = [];
  let listBuf: string[] = [];

  function flushList() {
    if (listBuf.length) {
      out.push(
        <ul key={out.length} className="list-disc pl-5 my-2 space-y-1">
          {listBuf.map((l, i) => (
            <li key={i}>{l.replace(/^[-*]\s+/, "")}</li>
          ))}
        </ul>,
      );
      listBuf = [];
    }
  }

  for (const line of lines) {
    if (line.startsWith("## ")) {
      flushList();
      out.push(
        <h3 key={out.length} className="font-semibold mt-4 mb-1 text-zinc-900">
          {line.slice(3)}
        </h3>,
      );
    } else if (line.startsWith("# ")) {
      flushList();
      out.push(
        <h2 key={out.length} className="font-bold mt-4 mb-2 text-zinc-900">
          {line.slice(2)}
        </h2>,
      );
    } else if (/^[-*]\s+/.test(line)) {
      listBuf.push(line);
    } else if (line.trim() === "") {
      flushList();
    } else {
      flushList();
      out.push(
        <p key={out.length} className="my-2 text-zinc-800">
          {line}
        </p>,
      );
    }
  }
  flushList();
  return <>{out}</>;
}
