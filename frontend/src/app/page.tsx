"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { CalendarView } from "@/components/CalendarView";
import { Chat } from "@/components/Chat";
import { PrefsUploader } from "@/components/PrefsUploader";
import { PrepBriefModal } from "@/components/PrepBriefModal";
import { useToast } from "@/components/Toast";

const STORAGE_KEY = "calendar-agent-session";

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [openPrepEventId, setOpenPrepEventId] = useState<string | null>(null);
  const [calendarRefresh, setCalendarRefresh] = useState(0);
  const [eventCount, setEventCount] = useState<number | null>(null);
  const toast = useToast();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get("session");
    const fromStorage = localStorage.getItem(STORAGE_KEY);
    const sid = fromUrl || fromStorage;
    if (fromUrl) {
      localStorage.setItem(STORAGE_KEY, fromUrl);
      window.history.replaceState({}, "", "/");
    }
    if (sid) setSessionId(sid);
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    api
      .checkSession(sessionId)
      .then((r) => {
        setUserEmail(r.email);
        setAuthError(null);
      })
      .catch(() => {
        setSessionId(null);
        localStorage.removeItem(STORAGE_KEY);
        setUserEmail(null);
      });
  }, [sessionId]);

  async function connectGoogle() {
    setAuthError(null);
    try {
      const { auth_url } = await api.startAuth();
      window.location.href = auth_url;
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setAuthError(msg);
      toast.error(msg);
    }
  }

  async function logout() {
    if (!sessionId) return;
    try {
      await api.logout(sessionId);
    } catch {
      // ignore
    }
    localStorage.removeItem(STORAGE_KEY);
    setSessionId(null);
    setUserEmail(null);
  }

  if (!sessionId) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-zinc-50 p-6">
        <div className="max-w-md w-full bg-white border border-zinc-200 rounded-xl p-8 shadow-sm">
          <h1 className="text-2xl font-semibold text-zinc-900 mb-2">Calendar Agent</h1>
          <p className="text-zinc-600 text-sm mb-6">
            Your calendar should answer questions, not just display them. Ask where your week went, find a time that works across five inboxes, or pull a prep brief from your own notes before the next meeting. Everything happens in one chat, against your real Google Workspace.
          </p>
          <button
            onClick={connectGoogle}
            className="w-full bg-zinc-900 text-white rounded-lg py-2.5 font-medium hover:bg-zinc-800"
          >
            Connect Google Workspace
          </button>
          {authError && <div className="mt-4 text-xs text-red-600">{authError}</div>}
          <p className="mt-6 text-xs text-zinc-500">
            Read-only on Drive. Calendar + Gmail draft scopes. No data is sent anywhere except Anthropic for reasoning and Google APIs for actions.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-zinc-50">
      <header className="border-b border-zinc-200 bg-white px-6 py-3 flex items-center justify-between">
        <h1 className="font-semibold text-zinc-900">Calendar Agent</h1>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-zinc-600">{userEmail || "loading..."}</span>
          <button onClick={logout} className="text-zinc-500 hover:text-zinc-900 text-xs">
            Sign out
          </button>
        </div>
      </header>

      <div className="grid grid-cols-12 gap-6 p-6 max-w-7xl mx-auto h-[calc(100vh-64px)]">
        <section className="col-span-5 bg-white border border-zinc-200 rounded-xl p-4 overflow-y-auto">
          <h2 className="font-semibold text-zinc-800 text-sm mb-3">Upcoming (14 days)</h2>
          <CalendarView
            sessionId={sessionId}
            onPrepClick={(id) => setOpenPrepEventId(id)}
            refreshKey={calendarRefresh}
            onEventsLoaded={(count) => setEventCount(count)}
          />
        </section>

        <section className="col-span-4 bg-white border border-zinc-200 rounded-xl p-4 flex flex-col">
          <Chat
            sessionId={sessionId}
            onActionMaybeAffectingCalendar={() => setCalendarRefresh((k) => k + 1)}
            calendarIsEmpty={eventCount === 0}
          />
        </section>

        <section className="col-span-3 bg-white border border-zinc-200 rounded-xl p-4 overflow-y-auto">
          <PrefsUploader sessionId={sessionId} />
        </section>
      </div>

      {openPrepEventId && (
        <PrepBriefModal
          sessionId={sessionId}
          eventId={openPrepEventId}
          onClose={() => setOpenPrepEventId(null)}
        />
      )}
    </main>
  );
}
