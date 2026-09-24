"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { WorkOrderDataContext, type WorkOrderData } from "@/data/context";
import type { LiveWorkOrder, Result, WorkOrderList, WorkOrderQuerySource } from "@/data/sources";
import type { WorkOrderDetail } from "@/lib/types";

/**
 * Control mode: real V2 WorkOrders, read-only.
 *
 * Loads what screens subscribe to and re-reads it every pollMs. It has no
 * commands, no runtime health and no telemetry: those surfaces render as
 * explicitly unavailable rather than falling back to simulated values.
 */

type Key = "list" | `wo:${string}`;
const LOADING: Result<never> = { status: "loading" };

export function V2WorkOrderProvider({
  source,
  pollMs = 5000,
  children,
}: {
  source: WorkOrderQuerySource;
  pollMs?: number;
  children: ReactNode;
}) {
  const [results, setResults] = useState<Partial<Record<Key, Result<WorkOrderDetail | WorkOrderList>>>>({});
  const subscribers = useRef(new Map<Key, number>());
  const inflight = useRef(new Set<Key>());

  const load = useCallback(
    async (key: Key) => {
      if (inflight.current.has(key)) return;
      inflight.current.add(key);
      try {
        const next = key === "list" ? await source.listWorkOrders() : await source.getWorkOrder(key.slice(3));
        setResults((prev) => (JSON.stringify(prev[key]) === JSON.stringify(next) ? prev : { ...prev, [key]: next }));
      } finally {
        inflight.current.delete(key);
      }
    },
    [source],
  );

  const subscribe = useCallback(
    (key: Key) => {
      const count = subscribers.current.get(key) ?? 0;
      subscribers.current.set(key, count + 1);
      if (count === 0) void load(key);
      return () => {
        const left = (subscribers.current.get(key) ?? 1) - 1;
        if (left <= 0) subscribers.current.delete(key);
        else subscribers.current.set(key, left);
      };
    },
    [load],
  );

  useEffect(() => {
    const timer = setInterval(() => {
      for (const key of subscribers.current.keys()) void load(key);
    }, pollMs);
    return () => clearInterval(timer);
  }, [load, pollMs]);

  // Keep object identity stable across renders for an unchanged payload.
  const liveCache = useRef(new WeakMap<WorkOrderDetail, LiveWorkOrder>());

  const value = useMemo<WorkOrderData>(
    () => ({
      source: "control",
      readWorkOrder: (id) => {
        const r = results[`wo:${id}`] as Result<WorkOrderDetail> | undefined;
        if (!r) return LOADING;
        if (r.status !== "ready") return r;
        let live = liveCache.current.get(r.data);
        if (!live) {
          live = { ...r.data, mode: "readonly", events: [], scriptIndex: 0 };
          liveCache.current.set(r.data, live);
        }
        return { status: "ready", data: live };
      },
      readList: () => (results.list as Result<WorkOrderList> | undefined) ?? LOADING,
      subscribe,
      commands: () => null,
      health: null,
      anyRunning: false,
    }),
    [results, subscribe],
  );

  return <WorkOrderDataContext.Provider value={value}>{children}</WorkOrderDataContext.Provider>;
}
