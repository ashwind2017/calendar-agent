"use client";

import { useState } from "react";
import { api, CreatedEvent, EventProposal } from "@/lib/api";
import { useToast } from "@/components/Toast";

type Props = {
  sessionId: string;
  proposal: EventProposal;
  onCreated?: (event: CreatedEvent) => void;
};

function formatRange(startIso: string, endIso: string): string {
  try {
    const start = new Date(startIso);
    const end = new Date(endIso);
    const sameDay =
      start.getFullYear() === end.getFullYear() &&
      start.getMonth() === end.getMonth() &&
      start.getDate() === end.getDate();
    const dateStr = start.toLocaleDateString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
    const startTime = start.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
    const endTime = end.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
    if (sameDay) {
      return `${dateStr}, ${startTime} to ${endTime}`;
    }
    const endDateStr = end.toLocaleDateString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
    return `${dateStr} ${startTime} to ${endDateStr} ${endTime}`;
  } catch {
    return `${startIso} to ${endIso}`;
  }
}

export function EventConfirmationCard({ sessionId, proposal, onCreated }: Props) {
  const [status, setStatus] = useState<"pending" | "creating" | "created" | "cancelled" | "error">(
    "pending",
  );
  const [createdEvent, setCreatedEvent] = useState<CreatedEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  async function confirm() {
    if (status !== "pending") return;
    setStatus("creating");
    setError(null);
    try {
      const res = await api.createEventFromProposal(sessionId, proposal);
      setCreatedEvent(res.event);
      setStatus("created");
      toast.success("Event created");
      if (onCreated) onCreated(res.event);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      setStatus("error");
      toast.error(msg);
    }
  }

  function cancel() {
    if (status === "pending" || status === "error") {
      setStatus("cancelled");
    }
  }

  if (status === "cancelled") {
    return (
      <div className="mt-2 rounded-lg border border-zinc-200 bg-zinc-50 p-3 text-xs text-zinc-500">
        Proposal dismissed.
      </div>
    );
  }

  if (status === "created" && createdEvent) {
    return (
      <div className="mt-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">
              Event created
            </div>
            <div className="mt-1 text-sm font-medium text-zinc-900">
              {createdEvent.summary || proposal.summary}
            </div>
            <div className="mt-0.5 text-xs text-zinc-600">
              {formatRange(proposal.start_iso, proposal.end_iso)}
            </div>
          </div>
          {createdEvent.html_link && (
            <a
              href={createdEvent.html_link}
              target="_blank"
              rel="noreferrer"
              className="shrink-0 rounded-lg border border-emerald-300 bg-white px-2.5 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
            >
              View event
            </a>
          )}
        </div>
      </div>
    );
  }

  const attendees = proposal.attendees || [];

  return (
    <div className="mt-2 rounded-lg border border-zinc-300 bg-white p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Proposed event
      </div>
      <div className="mt-1.5 text-sm font-medium text-zinc-900">{proposal.summary}</div>
      <div className="mt-0.5 text-xs text-zinc-600">
        {formatRange(proposal.start_iso, proposal.end_iso)}
      </div>
      {attendees.length > 0 && (
        <div className="mt-2 text-xs text-zinc-700">
          <span className="font-medium text-zinc-500">Attendees: </span>
          {attendees.join(", ")}
        </div>
      )}
      {proposal.location && (
        <div className="mt-1 text-xs text-zinc-700">
          <span className="font-medium text-zinc-500">Location: </span>
          {proposal.location}
        </div>
      )}
      {proposal.description && (
        <div className="mt-1 whitespace-pre-wrap text-xs text-zinc-700">
          <span className="font-medium text-zinc-500">Notes: </span>
          {proposal.description}
        </div>
      )}

      {status === "error" && error && (
        <div className="mt-2 rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">
          Failed to create event: {error}
        </div>
      )}

      <div className="mt-3 flex gap-2">
        <button
          onClick={confirm}
          disabled={status === "creating"}
          className="rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-50"
        >
          {status === "creating" ? "Creating..." : "Confirm and create"}
        </button>
        <button
          onClick={cancel}
          disabled={status === "creating"}
          className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
