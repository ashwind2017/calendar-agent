"use client";

import { useState, useRef, useEffect } from "react";
import { api, ChatResponse, EventProposal } from "@/lib/api";
import { EventConfirmationCard } from "@/components/EventConfirmationCard";

type Message = {
  role: "user" | "assistant";
  content: string;
  toolTrace?: ChatResponse["tool_trace"];
  proposals?: EventProposal[];
};

function extractProposals(trace: ChatResponse["tool_trace"]): EventProposal[] {
  const proposals: EventProposal[] = [];
  for (const t of trace) {
    if (t.tool !== "propose_calendar_event") continue;
    const input = t.input || {};
    const summary = typeof input.summary === "string" ? input.summary : "";
    const startIso = typeof input.start_iso === "string" ? input.start_iso : "";
    const endIso = typeof input.end_iso === "string" ? input.end_iso : "";
    if (!summary || !startIso || !endIso) continue;
    const attendeesRaw = input.attendees;
    const attendees = Array.isArray(attendeesRaw)
      ? attendeesRaw.filter((x): x is string => typeof x === "string")
      : undefined;
    proposals.push({
      summary,
      start_iso: startIso,
      end_iso: endIso,
      attendees,
      description: typeof input.description === "string" ? input.description : "",
      location: typeof input.location === "string" ? input.location : "",
    });
  }
  return proposals;
}

type Props = {
  sessionId: string;
  onActionMaybeAffectingCalendar?: () => void;
  calendarIsEmpty?: boolean;
};

const SUGGESTED_PROMPTS = [
  "What does my week look like?",
  "How much time am I spending in meetings?",
  "Find 30 min with alice@example.com this week, mornings protected",
  "Generate a prep brief for my next meeting",
];

export function Chat({ sessionId, onActionMaybeAffectingCalendar, calendarIsEmpty }: Props) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Hi! Ask me about your calendar. I can summarize your week, find time with multiple people, draft scheduling emails, and analyze how you're spending your time.",
    },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [showTrace, setShowTrace] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const hasUserMessage = messages.some((m) => m.role === "user");
  const showSuggestions = !hasUserMessage && !sending;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function sendText(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: trimmed }]);
    setSending(true);
    try {
      const res = await api.chat(sessionId, trimmed);
      const proposals = extractProposals(res.tool_trace);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: res.answer,
          toolTrace: res.tool_trace,
          proposals: proposals.length > 0 ? proposals : undefined,
        },
      ]);
      // If tools that change calendar state ran, ask parent to refresh
      const wroteSomething = res.tool_trace.some((t) =>
        ["create_email_draft", "create_calendar_event"].includes(t.tool),
      );
      if (wroteSomething && onActionMaybeAffectingCalendar) {
        onActionMaybeAffectingCalendar();
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setMessages((m) => [...m, { role: "assistant", content: `Error: ${msg}` }]);
    } finally {
      setSending(false);
    }
  }

  function send() {
    return sendText(input);
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-2 px-1">
        <h2 className="font-semibold text-zinc-800">Chat</h2>
        <button
          onClick={() => setShowTrace((v) => !v)}
          className="text-xs text-zinc-500 hover:text-zinc-800"
        >
          {showTrace ? "Hide" : "Show"} tool trace
        </button>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto space-y-3 border border-zinc-200 rounded-lg p-3 bg-zinc-50"
      >
        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                m.role === "user"
                  ? "bg-zinc-900 text-white whitespace-pre-wrap"
                  : "bg-white border border-zinc-200 text-zinc-900"
              }`}
            >
              {m.role === "assistant" ? <AssistantText text={m.content} /> : m.content}
              {m.role === "assistant" && m.proposals && m.proposals.length > 0 && (
                <div className="space-y-2">
                  {m.proposals.map((p, pi) => (
                    <EventConfirmationCard
                      key={pi}
                      sessionId={sessionId}
                      proposal={p}
                      onCreated={() => {
                        if (onActionMaybeAffectingCalendar) onActionMaybeAffectingCalendar();
                      }}
                    />
                  ))}
                </div>
              )}
              {showTrace && m.toolTrace && m.toolTrace.length > 0 && (
                <div className="mt-2 pt-2 border-t border-zinc-200 text-[10px] text-zinc-500 space-y-1">
                  {m.toolTrace.map((t, idx) => (
                    <div key={idx} className="font-mono">
                      <span className="font-semibold">{t.tool}</span>
                      <span className="ml-1">{JSON.stringify(t.input).slice(0, 80)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex justify-start">
            <div className="bg-white border border-zinc-200 rounded-lg px-3 py-2 text-sm text-zinc-500">
              thinking...
            </div>
          </div>
        )}
        {showSuggestions && (
          <div className="pt-1">
            {calendarIsEmpty && (
              <div className="mb-3 text-xs text-zinc-600 bg-white border border-dashed border-zinc-200 rounded-lg px-3 py-2">
                Your calendar is empty for the next 14 days. Try uploading some notes on the right to get prep briefs, or come back when you have meetings scheduled.
              </div>
            )}
            <div className="text-[11px] uppercase tracking-wide text-zinc-500 mb-2 px-0.5">
              Try one of these
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {SUGGESTED_PROMPTS.map((p) => (
                <button
                  key={p}
                  onClick={() => sendText(p)}
                  disabled={sending}
                  className="text-left text-xs text-zinc-700 bg-white border border-zinc-200 rounded-lg px-3 py-2 hover:border-zinc-400 hover:bg-zinc-100 transition disabled:opacity-50"
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="mt-3 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Ask me anything about your calendar..."
          disabled={sending}
          className="flex-1 border border-zinc-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-900"
        />
        <button
          onClick={send}
          disabled={sending || !input.trim()}
          className="px-4 py-2 bg-zinc-900 text-white rounded-lg text-sm disabled:opacity-50"
        >
          Send
        </button>
      </div>

      <div className="mt-2 text-xs text-zinc-500">
        Try: &quot;What&apos;s my week look like?&quot; &middot; &quot;Find 30 min with alice@x.com this week, mornings protected&quot;
      </div>
    </div>
  );
}

// Light markdown renderer for assistant responses.
// Handles: headers (## / ###), bullet lists (- or *), bold (**x**), code (`x`), and paragraphs.
function AssistantText({ text }: { text: string }) {
  const lines = text.split("\n");
  const nodes: React.ReactNode[] = [];
  let listBuf: string[] = [];

  function flushList() {
    if (listBuf.length) {
      nodes.push(
        <ul key={nodes.length} className="list-disc pl-5 my-1 space-y-0.5">
          {listBuf.map((l, i) => (
            <li key={i}>{inline(l.replace(/^[-*]\s+/, ""))}</li>
          ))}
        </ul>,
      );
      listBuf = [];
    }
  }

  function inline(s: string) {
    // very light: bold + inline code
    const parts: React.ReactNode[] = [];
    const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
    let last = 0;
    let m: RegExpExecArray | null;
    let i = 0;
    while ((m = re.exec(s)) !== null) {
      if (m.index > last) parts.push(s.slice(last, m.index));
      const t = m[0];
      if (t.startsWith("**")) {
        parts.push(<strong key={i++}>{t.slice(2, -2)}</strong>);
      } else {
        parts.push(
          <code key={i++} className="bg-zinc-100 rounded px-1 py-0.5 text-[12px]">
            {t.slice(1, -1)}
          </code>,
        );
      }
      last = m.index + t.length;
    }
    if (last < s.length) parts.push(s.slice(last));
    return parts;
  }

  for (const line of lines) {
    if (/^###\s+/.test(line)) {
      flushList();
      nodes.push(
        <div key={nodes.length} className="font-semibold mt-2 text-zinc-900">
          {line.replace(/^###\s+/, "")}
        </div>,
      );
    } else if (/^##\s+/.test(line)) {
      flushList();
      nodes.push(
        <div key={nodes.length} className="font-semibold mt-2 text-zinc-900">
          {line.replace(/^##\s+/, "")}
        </div>,
      );
    } else if (/^[-*]\s+/.test(line)) {
      listBuf.push(line);
    } else if (line.trim() === "") {
      flushList();
    } else {
      flushList();
      nodes.push(
        <p key={nodes.length} className="my-1">
          {inline(line)}
        </p>,
      );
    }
  }
  flushList();
  return <>{nodes}</>;
}
