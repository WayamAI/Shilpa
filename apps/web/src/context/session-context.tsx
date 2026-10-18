"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, errText, type Health, type Me } from "@/lib/api";

interface SessionValue {
  me: Me | null;
  health: Health | null;
  /** Set when the API cannot be reached or rejects the session. */
  error: string | null;
  refresh: () => void;
}

const SessionContext = createContext<SessionValue | null>(null);

/** Who is signed in and whether the planner is online, loaded once for the shell. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.me(), api.health()])
      .then(([m, h]) => {
        if (cancelled) return;
        setMe(m);
        setHealth(h);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(errText(e));
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  return <SessionContext.Provider value={{ me, health, error, refresh }}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
