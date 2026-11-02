"use client";

import { useEffect, useState } from "react";

import { api, errText, type NeedsYouItem } from "@/lib/api";

export type NeedsYouState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; items: NeedsYouItem[] };

/** The inbox from GET /v1/needs-you. Refetches when `attempt` or `refreshKey` changes. */
export function useNeedsYou(attempt = 0, refreshKey?: string): NeedsYouState {
  const [state, setState] = useState<NeedsYouState>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    api
      .needsYou()
      .then((r) => !cancelled && setState({ status: "ready", items: r.items }))
      .catch((e) => !cancelled && setState({ status: "error", message: errText(e) }));
    return () => {
      cancelled = true;
    };
  }, [attempt, refreshKey]);
  return state;
}
