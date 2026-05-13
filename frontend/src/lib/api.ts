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

// Custom error type so callers can branch on status when useful.
export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(message: string, status: number, detail: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function friendlyMessage(status: number, detail: string): string {
  if (status === 401) return "Your session expired. Please reconnect Google.";
  if (status === 403) return "You don't have access to that resource.";
  if (status === 404) return "We couldn't find what you were looking for.";
  if (status === 429) return "Too many requests. Wait a moment and try again.";
  if (status === 502 || status === 503 || status === 504) {
    return "Couldn't reach the calendar service. Try again in a moment.";
  }
  if (status >= 500) return "Something went wrong on the server. Try again.";
  // 4xx with backend-provided detail is usually informative enough to surface.
  if (detail && detail !== "" && detail !== "Unknown error") return detail;
  return "Request failed. Please try again.";
}

async function jsonOrThrow<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = "";
    try {
      const d = await r.json();
      detail = (d && (d.detail || d.message)) || JSON.stringify(d);
    } catch {
      detail = r.statusText || "";
    }
    throw new ApiError(friendlyMessage(r.status, detail), r.status, detail);
  }
  return r.json();
}

async function safeFetch(input: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (e: unknown) {
    const detail = e instanceof Error ? e.message : String(e);
    throw new ApiError(
      "Connection error. Check your network and retry.",
      0,
      detail,
    );
  }
}

export const api = {
  async startAuth(): Promise<{ auth_url: string; state: string }> {
    return jsonOrThrow(await safeFetch(`${API_BASE}/auth/start`));
  },

  async checkSession(sessionId: string): Promise<{ ok: boolean; email: string }> {
    return jsonOrThrow(await safeFetch(`${API_BASE}/auth/check?session_id=${sessionId}`));
  },

  async logout(sessionId: string): Promise<{ ok: boolean }> {
    return jsonOrThrow(
      await safeFetch(`${API_BASE}/auth/logout?session_id=${sessionId}`, { method: "POST" }),
    );
  },

  async getUpcoming(sessionId: string, days = 7): Promise<{ events: CalendarEvent[] }> {
    return jsonOrThrow(
      await safeFetch(`${API_BASE}/calendar/upcoming?session_id=${sessionId}&days_ahead=${days}`),
    );
  },

  async chat(sessionId: string, message: string): Promise<ChatResponse> {
    return jsonOrThrow(
      await safeFetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message }),
      }),
    );
  },

  async uploadPrefsText(sessionId: string, source: string, content: string): Promise<{ ok: boolean; entries: number }> {
    return jsonOrThrow(
      await safeFetch(`${API_BASE}/rag/upload-text`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, source, content }),
      }),
    );
  },

  async ragList(sessionId: string): Promise<{ sources: Record<string, number>; total_chunks: number }> {
    return jsonOrThrow(await safeFetch(`${API_BASE}/rag/list?session_id=${sessionId}`));
  },

  async ragClear(sessionId: string): Promise<{ ok: boolean }> {
    return jsonOrThrow(
      await safeFetch(`${API_BASE}/rag/clear?session_id=${sessionId}`, { method: "POST" }),
    );
  },

  async prepBrief(sessionId: string, eventId: string): Promise<PrepBrief> {
    return jsonOrThrow(
      await safeFetch(`${API_BASE}/prep/${eventId}?session_id=${sessionId}`),
    );
  },

  async createEventFromProposal(
    sessionId: string,
    proposal: EventProposal,
  ): Promise<{ ok: boolean; event: CreatedEvent }> {
    return jsonOrThrow(
      await safeFetch(`${API_BASE}/calendar/create-from-proposal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, proposal }),
      }),
    );
  },
};
