"use client";

import { useEffect, useState } from "react";
import { api, CalendarEvent } from "@/lib/api";

type Props = {
  sessionId: string;
  onPrepClick: (eventId: string) => void;
  refreshKey?: number;
};

function formatRange(start: string, end: string): string {
  try {
    const s = new Date(start);
    const e = new Date(end);
    const date = s.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
    const sTime = s.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    const eTime = e.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    return `${date}, ${sTime} – ${eTime}`;
  } catch {
    return `${start} → ${end}`;
  }
}

function groupByDay(events: CalendarEvent[]): Record<string, CalendarEvent[]> {
  const out: Record<string, CalendarEvent[]> = {};
  for (const ev of events) {
    try {
      const day = new Date(ev.start).toDateString();
      out[day] = out[day] || [];
      out[day].push(ev);
    } catch {
      // skip
    }
  }
  return out;
}

export function CalendarView({ sessionId, onPrepClick, refreshKey = 0 }: Props) {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getUpcoming(sessionId, 14)
      .then((r) => {
        if (!cancelled) setEvents(r.events || []);
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
  }, [sessionId, refreshKey]);

  if (loading) return <div className="text-sm text-zinc-500">Loading calendar...</div>;
  if (error) return <div className="text-sm text-red-600">Calendar error: {error}</div>;
  if (events.length === 0) return <div className="text-sm text-zinc-500">No upcoming events in the next 14 days.</div>;

  const grouped = groupByDay(events);
  const days = Object.keys(grouped).sort((a, b) => new Date(a).getTime() - new Date(b).getTime());

  return (
    <div className="space-y-6">
      {days.map((day) => (
        <div key={day}>
          <h3 className="font-semibold text-zinc-800 text-sm mb-2 sticky top-0 bg-white py-1">
            {new Date(day).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
          </h3>
          <ul className="space-y-2">
            {grouped[day].map((ev) => (
              <li
                key={ev.id}
                className="border border-zinc-200 rounded-lg p-3 hover:border-zinc-300 transition group"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-zinc-900 truncate">{ev.summary}</div>
                    <div className="text-xs text-zinc-500 mt-1">{formatRange(ev.start, ev.end)}</div>
                    {ev.attendees.length > 0 && (
                      <div className="text-xs text-zinc-600 mt-1 truncate">
                        {ev.attendees.length} attendee{ev.attendees.length === 1 ? "" : "s"}
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => onPrepClick(ev.id)}
                    className="text-xs px-2 py-1 bg-zinc-900 text-white rounded opacity-0 group-hover:opacity-100 transition"
                  >
                    Prep brief
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
