"use client";

import { createContext, useContext, useEffect } from "react";

import type { LiveWorkOrder, Result, WorkOrderCommandSource, WorkOrderList } from "@/data/sources";
import type { CommandResult } from "@/data/control-source";
import type { DataSource, OwnerCommand, SystemHealth } from "@/lib/types";

/**
 * What every Mission Control screen reads from. Implemented by
 * FixtureWorkOrderProvider (demo) and V2WorkOrderProvider (control, read-only).
 * Screens use the hooks below and never know which one is mounted.
 */
export interface WorkOrderData {
  source: DataSource;
  readWorkOrder(id: string): Result<LiveWorkOrder>;
  readList(): Result<WorkOrderList>;
  /** Start (and keep) loading a key while a screen shows it. Returns the unsubscribe. */
  subscribe(key: "list" | `wo:${string}`): () => void;
  /** Null when the source cannot change this WorkOrder (always null in control mode). */
  commands(id: string): WorkOrderCommandSource | null;
  /** Null when runtime health is not available from this source. */
  health: SystemHealth | null;
  /** True only while the source reports autonomous work in progress. */
  anyRunning: boolean;
  /** Control mode: whether the control event stream is pushing changes. Null in demo. */
  link: LinkState | null;
  /**
   * Control mode owner commands (ADR-038). Null when this source cannot send them
   * (demo, or the server has no owner token), with the reason in ownerCommandsOff.
   */
  sendCommand: ((id: string, command: OwnerCommand, expectedVersion: number, message?: string) => Promise<CommandResult>) | null;
  ownerCommandsOff: string | null;
}

/** live: changes are pushed. connecting / polling: re-read on a timer until the stream is up. */
export type LinkState = "connecting" | "live" | "polling";

export const WorkOrderDataContext = createContext<WorkOrderData | null>(null);

function useData(): WorkOrderData {
  const ctx = useContext(WorkOrderDataContext);
  if (!ctx) throw new Error("Mission Control hooks need a WorkOrder data provider");
  return ctx;
}

export function useDataSource() {
  return useData().source;
}

export function useWorkOrderResult(id: string | undefined): Result<LiveWorkOrder> {
  const data = useData();
  const { subscribe } = data;
  useEffect(() => (id ? subscribe(`wo:${id}`) : undefined), [subscribe, id]);
  return id ? data.readWorkOrder(id) : { status: "not_found" };
}

/** The WorkOrder once loaded; undefined while loading, missing, or failed. */
export function useLiveWorkOrder(id: string | undefined): LiveWorkOrder | undefined {
  const result = useWorkOrderResult(id);
  return result.status === "ready" ? result.data : undefined;
}

export function useWorkOrderList(): Result<WorkOrderList> {
  const data = useData();
  const { subscribe } = data;
  useEffect(() => subscribe("list"), [subscribe]);
  return data.readList();
}

export function useRunCommands(id: string | undefined): WorkOrderCommandSource | null {
  const data = useData();
  return id ? data.commands(id) : null;
}

export function useHealth(): SystemHealth | null {
  return useData().health;
}

export function useAnyRunning(): boolean {
  return useData().anyRunning;
}

export function useLink(): LinkState | null {
  return useData().link;
}

export function useOwnerCommands() {
  const { sendCommand, ownerCommandsOff } = useData();
  return { sendCommand, ownerCommandsOff };
}
