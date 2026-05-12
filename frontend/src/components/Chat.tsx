"use client";

import { useState, useRef, useEffect } from "react";
import { api, ChatResponse } from "@/lib/api";

type Message = {
  role: "user" | "assistant";
  content: string;
  toolTrace?: ChatResponse["tool_trace"];
};

type Props = {
  sessionId: string;
  onActionMaybeAffectingCalendar?: () => void;
};

export function Chat({ sessionId, onActionMaybeAffectingCalendar }: Props) {
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

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function send() {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setSending(true);
    try {
      const res = await api.chat(sessionId, text);
      setMessages((m) => [
        ...m,
        { role: "assistant", content: res.answer, toolTrace: res.tool_trace },
      ]);
      // If tools that change calendar state ran, ask parent to refresh
      const wroteSomething = res.tool_trace.some((t) =>
        ["create_email_draft"].includes(t.tool),
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
              className={`max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
                m.role === "user"
                  ? "bg-zinc-900 text-white"
                  : "bg-white border border-zinc-200 text-zinc-900"
              }`}
            >
              {m.content}
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
