"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

type ToastKind = "success" | "error" | "info";

type ToastItem = {
  id: number;
  kind: ToastKind;
  message: string;
};

type ToastApi = {
  success: (msg: string) => void;
  error: (msg: string) => void;
  info: (msg: string) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

const AUTO_DISMISS_MS = 4000;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const idRef = useRef(0);
  const timersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: number) => {
    setToasts((cur) => cur.filter((t) => t.id !== id));
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      idRef.current += 1;
      const id = idRef.current;
      setToasts((cur) => [...cur, { id, kind, message }]);
      const timer = setTimeout(() => {
        setToasts((cur) => cur.filter((t) => t.id !== id));
        timersRef.current.delete(id);
      }, AUTO_DISMISS_MS);
      timersRef.current.set(id, timer);
    },
    [],
  );

  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      for (const t of timers.values()) clearTimeout(t);
      timers.clear();
    };
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      success: (msg: string) => push("success", msg),
      error: (msg: string) => push("error", msg),
      info: (msg: string) => push("info", msg),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (ctx) return ctx;
  // Fallback no-op so callers still work outside the provider (e.g. tests).
  return {
    success: () => {},
    error: () => {},
    info: () => {},
  };
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: number) => void;
}) {
  return (
    <div
      aria-live="polite"
      aria-atomic="true"
      className="fixed top-4 right-4 z-[100] flex flex-col gap-2 max-w-sm w-[calc(100vw-2rem)] sm:w-auto pointer-events-none"
    >
      {toasts.map((t) => (
        <ToastCard key={t.id} toast={t} onDismiss={() => onDismiss(t.id)} />
      ))}
    </div>
  );
}

function ToastCard({ toast, onDismiss }: { toast: ToastItem; onDismiss: () => void }) {
  const styles = kindStyles(toast.kind);
  return (
    <div
      role={toast.kind === "error" ? "alert" : "status"}
      className={`pointer-events-auto rounded-lg shadow-md border px-3 py-2 text-sm flex items-start gap-2 ${styles.container}`}
    >
      <div className={`mt-0.5 shrink-0 w-1.5 h-1.5 rounded-full ${styles.dot}`} aria-hidden />
      <div className="flex-1 min-w-0 break-words">{toast.message}</div>
      <button
        onClick={onDismiss}
        aria-label="Dismiss notification"
        className={`shrink-0 text-xs leading-none px-1 ${styles.close}`}
      >
        {"×"}
      </button>
    </div>
  );
}

function kindStyles(kind: ToastKind): { container: string; dot: string; close: string } {
  switch (kind) {
    case "success":
      return {
        container: "bg-green-50 border-green-200 text-green-900",
        dot: "bg-green-500",
        close: "text-green-700 hover:text-green-900",
      };
    case "error":
      return {
        container: "bg-red-50 border-red-200 text-red-900",
        dot: "bg-red-500",
        close: "text-red-700 hover:text-red-900",
      };
    case "info":
    default:
      return {
        container: "bg-zinc-50 border-zinc-200 text-zinc-900",
        dot: "bg-zinc-500",
        close: "text-zinc-600 hover:text-zinc-900",
      };
  }
}
