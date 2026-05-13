const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type CalendarEvent = {
  id: string;
  summary: string;
  description: string;
  start: string;
  end: string;
  attendees: { email: string; responseStatus?: string }[];
  organizer?: string;
  location?: string;
  hangoutLink?: string;
  html_link?: string;
  recurring_event_id?: string;
};

export type ChatResponse = {
  ok: boolean;
  answer: string;
  tool_trace: { tool: string; input: Record<string, unknown>; result_preview: string }[];
};

export type EventProposal = {
  summary: string;
  start_iso: string;
  end_iso: string;
  attendees?: string[];
  description?: string;
  location?: string;
};

export type CreatedEvent = {
  id?: string;
  html_link?: string;
  summary?: string;
  start?: string;
  end?: string;
};

export type PrepBrief = {
  ok: boolean;
  meeting: {
    id: string;
    summary: string;
    start: string;
    end: string;
    attendees: string[];
    html_link?: string;
  };
  brief_markdown: string;
  data_sources: {
    past_meetings_count: number;
    rag_chunks_used: number;
    attendees_resolved: number;
  };
};

async function jsonOrThrow<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail: string;
    try {
      const d = await r.json();
      detail = d.detail || JSON.stringify(d);
    } catch {
      detail = r.statusText;
    }
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json();
}

export const api = {
  async startAuth(): Promise<{ auth_url: string; state: string }> {
    return jsonOrThrow(await fetch(`${API_BASE}/auth/start`));
  },

  async checkSession(sessionId: string): Promise<{ ok: boolean; email: string }> {
    return jsonOrThrow(await fetch(`${API_BASE}/auth/check?session_id=${sessionId}`));
  },

  async logout(sessionId: string): Promise<{ ok: boolean }> {
    return jsonOrThrow(await fetch(`${API_BASE}/auth/logout?session_id=${sessionId}`, { method: "POST" }));
  },

  async getUpcoming(sessionId: string, days = 7): Promise<{ events: CalendarEvent[] }> {
    return jsonOrThrow(
      await fetch(`${API_BASE}/calendar/upcoming?session_id=${sessionId}&days_ahead=${days}`),
    );
  },

  async chat(sessionId: string, message: string): Promise<ChatResponse> {
    return jsonOrThrow(
      await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message }),
      }),
    );
  },

  async uploadPrefsText(sessionId: string, source: string, content: string): Promise<{ ok: boolean; entries: number }> {
    return jsonOrThrow(
      await fetch(`${API_BASE}/rag/upload-text`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, source, content }),
      }),
    );
  },

  async ragList(sessionId: string): Promise<{ sources: Record<string, number>; total_chunks: number }> {
    return jsonOrThrow(await fetch(`${API_BASE}/rag/list?session_id=${sessionId}`));
  },

  async ragClear(sessionId: string): Promise<{ ok: boolean }> {
    return jsonOrThrow(await fetch(`${API_BASE}/rag/clear?session_id=${sessionId}`, { method: "POST" }));
  },

  async prepBrief(sessionId: string, eventId: string): Promise<PrepBrief> {
    return jsonOrThrow(await fetch(`${API_BASE}/prep/${eventId}?session_id=${sessionId}`));
  },

  async createEventFromProposal(
    sessionId: string,
    proposal: EventProposal,
  ): Promise<{ ok: boolean; event: CreatedEvent }> {
    return jsonOrThrow(
      await fetch(`${API_BASE}/calendar/create-from-proposal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, proposal }),
      }),
    );
  },
};
