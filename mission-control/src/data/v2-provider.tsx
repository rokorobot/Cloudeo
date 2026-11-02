"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { WorkOrderDataContext, type LinkState, type WorkOrderData } from "@/data/context";
import type { LiveWorkOrder, Result, WorkOrderList, WorkOrderQuerySource } from "@/data/sources";
import type { WorkOrderDetail } from "@/lib/types";

/**
 * Control mode: real V2 WorkOrders, read-only, kept current in real time.
 *
 * Screens subscribe to keys; the provider loads them and listens to the
 * control event stream (/api/control/stream). Each event names the WorkOrder
 * that changed, and the provider re-reads that WorkOrder and the list through
 * the query source, so the adapter stays the only mapping. While the stream is
 * down it falls back to re-reading every pollMs.
 *
 * It has no commands, no runtime health and no telemetry: those surfaces
 * render as explicitly unavailable rather than falling back to simulated values.
 */

type Key = "list" | `wo:${string}`;
const LOADING: Result<never> = { status: "loading" };

/** The part of EventSource the provider uses; injectable for tests. */
export interface ControlStream {
  readonly readyState: number;
  onopen: ((ev: Event) => unknown) | null;
  onerror: ((ev: Event) => unknown) | null;
  addEventListener(type: string, listener: (ev: MessageEvent) => void): void;
  close(): void;
}

const CLOSED = 2;
const openEventSource = (): ControlStream => new EventSource("/api/control/stream");

export function V2WorkOrderProvider({
  source,
  pollMs = 5000,
  reconnectMs = 5000,
  openStream = openEventSource,
  children,
}: {
  source: WorkOrderQuerySource;
  pollMs?: number;
  reconnectMs?: number;
  openStream?: (() => ControlStream) | null;
  children: ReactNode;
}) {
  const [results, setResults] = useState<Partial<Record<Key, Result<WorkOrderDetail | WorkOrderList>>>>({});
  const [link, setLink] = useState<LinkState>(openStream ? "connecting" : "polling");
  const subscribers = useRef(new Map<Key, number>());
  const inflight = useRef(new Set<Key>());
  const stale = useRef(new Set<Key>());

  const load = useCallback(
    async (key: Key) => {
      // A change that lands mid-request is not lost: re-read once it finishes.
      if (inflight.current.has(key)) {
        stale.current.add(key);
        return;
      }
      inflight.current.add(key);
      try {
        do {
          stale.current.delete(key);
          const next = key === "list" ? await source.listWorkOrders() : await source.getWorkOrder(key.slice(3));
          setResults((prev) => (JSON.stringify(prev[key]) === JSON.stringify(next) ? prev : { ...prev, [key]: next }));
        } while (stale.current.has(key));
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
    if (!openStream) return;
    let stream: ControlStream | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;
    const reloadAll = () => {
      for (const key of subscribers.current.keys()) void load(key);
    };
    const connect = () => {
      stream = openStream();
      stream.onopen = () => setLink("live");
      stream.onerror = () => {
        setLink("polling");
        // EventSource retries network drops itself; after an HTTP error it gives up.
        if (stream?.readyState === CLOSED && !disposed) retry = setTimeout(connect, reconnectMs);
      };
      stream.addEventListener("ready", () => {
        setLink("live");
        reloadAll();
      });
      stream.addEventListener("work-order", (ev) => {
        let id: unknown;
        try {
          id = JSON.parse(ev.data).workOrderId;
        } catch {
          id = undefined;
        }
        if (subscribers.current.has("list")) void load("list");
        if (typeof id !== "string") reloadAll();
        else if (subscribers.current.has(`wo:${id}`)) void load(`wo:${id}`);
      });
      stream.addEventListener("unavailable", () => setLink("polling"));
    };
    connect();
    return () => {
      disposed = true;
      clearTimeout(retry);
      stream?.close();
    };
  }, [openStream, load, reconnectMs]);

  // Fallback while the stream is down: re-read what is on screen.
  useEffect(() => {
    if (link === "live") return;
    const timer = setInterval(() => {
      for (const key of subscribers.current.keys()) void load(key);
    }, pollMs);
    return () => clearInterval(timer);
  }, [load, pollMs, link]);

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
      link,
    }),
    [results, subscribe, link],
  );

  return <WorkOrderDataContext.Provider value={value}>{children}</WorkOrderDataContext.Provider>;
}
