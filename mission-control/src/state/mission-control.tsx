"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  type ReactNode,
} from "react";

import { WORK_ORDERS } from "@/fixtures/work-orders";
import type {
  ActivityEvent,
  LifecycleStage,
  StageStatus,
  WorkOrderDetail,
  WorkOrderState,
} from "@/lib/types";

/**
 * Client-side simulation of live WorkOrder progress.
 *
 * This is the single place UI state lives in this milestone. It is a local
 * stand-in for a future control-store subscription: components read through
 * the hooks below and never touch timers or fixtures directly, so swapping in
 * a streaming backend only changes this file.
 */

export type RunMode = "running" | "paused" | "operator" | "stopped" | "static";

interface LiveRun {
  mode: RunMode;
  elapsedSec: number;
  costUsd: number;
  steps: number;
  evidenceCount: number;
  events: ActivityEvent[];
  scriptIndex: number;
  eventSeq: number;
}

interface State {
  runs: Record<string, LiveRun>;
  paletteOpen: boolean;
  inspectorOpen: boolean;
}

type Action =
  | { type: "tick" }
  | { type: "step"; id: string }
  | { type: "pause"; id: string }
  | { type: "resume"; id: string }
  | { type: "takeControl"; id: string }
  | { type: "handBack"; id: string }
  | { type: "stop"; id: string }
  | { type: "palette"; open: boolean }
  | { type: "inspector"; open: boolean };

const MAX_EVENTS = 40;
const STEP_COST_USD = 0.02;

export function initialState(): State {
  const runs: Record<string, LiveRun> = {};
  for (const wo of Object.values(WORK_ORDERS)) {
    const live = !!wo.execution && wo.state === "executing";
    runs[wo.id] = {
      mode: live ? "running" : "static",
      elapsedSec: wo.elapsedSec,
      costUsd: wo.cost.usd,
      steps: wo.steps,
      evidenceCount: wo.evidenceCount,
      events: wo.execution?.seedEvents ?? [],
      scriptIndex: 0,
      eventSeq: 0,
    };
  }
  return { runs, paletteOpen: false, inspectorOpen: true };
}

function withEvent(run: LiveRun, e: Omit<ActivityEvent, "id" | "atSec">): LiveRun {
  const event: ActivityEvent = { ...e, id: `e${run.eventSeq}`, atSec: run.elapsedSec };
  return {
    ...run,
    eventSeq: run.eventSeq + 1,
    events: [...run.events, event].slice(-MAX_EVENTS),
  };
}

export function reducer(state: State, action: Action): State {
  if (action.type === "palette") return { ...state, paletteOpen: action.open };
  if (action.type === "inspector") return { ...state, inspectorOpen: action.open };

  if (action.type === "tick") {
    let changed = false;
    const runs = { ...state.runs };
    for (const [id, run] of Object.entries(runs)) {
      if (run.mode === "running" || run.mode === "operator") {
        runs[id] = { ...run, elapsedSec: run.elapsedSec + 1 };
        changed = true;
      }
    }
    return changed ? { ...state, runs } : state;
  }

  const run = state.runs[action.id];
  if (!run) return state;
  const set = (next: LiveRun): State => ({ ...state, runs: { ...state.runs, [action.id]: next } });

  switch (action.type) {
    case "step": {
      const script = WORK_ORDERS[action.id]?.execution?.script;
      if (run.mode !== "running" || !script?.length) return state;
      const step = script[run.scriptIndex % script.length];
      const next = withEvent(run, { kind: "step", text: step.text, detail: step.detail });
      return set({
        ...next,
        scriptIndex: run.scriptIndex + 1,
        steps: run.steps + 1,
        costUsd: +(run.costUsd + STEP_COST_USD).toFixed(2),
        evidenceCount: run.evidenceCount + (step.producesEvidence ? 1 : 0),
      });
    }
    case "pause":
      if (run.mode !== "running") return state;
      return set(withEvent({ ...run, mode: "paused" }, { kind: "system", text: "Paused by operator", detail: "current step finished · nothing new starts" }));
    case "resume":
      if (run.mode !== "paused") return state;
      return set(withEvent({ ...run, mode: "running" }, { kind: "system", text: "Resumed", detail: "autonomous execution continues from last step" }));
    case "takeControl":
      if (run.mode !== "running" && run.mode !== "paused") return state;
      return set(withEvent({ ...run, mode: "operator" }, { kind: "operator", text: "Operator took control", detail: "agent paused · browser actions recorded as evidence" }));
    case "handBack":
      if (run.mode !== "operator") return state;
      return set(
        withEvent({ ...run, mode: "running", evidenceCount: run.evidenceCount + 1 }, {
          kind: "operator",
          text: "Control returned to agent",
          detail: "operator session attached to block evidence",
        }),
      );
    case "stop":
      if (run.mode === "stopped" || run.mode === "static") return state;
      return set(withEvent({ ...run, mode: "stopped" }, { kind: "system", text: "Stopped by operator", detail: "candidate discarded · accepted checkpoint unchanged" }));
  }
}

interface ContextValue {
  state: State;
  dispatch: (a: Action) => void;
}

const Ctx = createContext<ContextValue | null>(null);

export function MissionControlProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);

  useEffect(() => {
    const clock = setInterval(() => dispatch({ type: "tick" }), 1000);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const stepper = setInterval(() => {
      for (const id of Object.keys(WORK_ORDERS)) dispatch({ type: "step", id });
    }, reduce ? 4000 : 2400);
    return () => {
      clearInterval(clock);
      clearInterval(stepper);
    };
  }, []);

  const value = useMemo(() => ({ state, dispatch }), [state]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

function useCtx() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useMissionControl must be used inside MissionControlProvider");
  return ctx;
}

export interface LiveWorkOrder extends WorkOrderDetail {
  mode: RunMode;
  events: ActivityEvent[];
  scriptIndex: number;
}

function liveState(base: WorkOrderState, mode: RunMode): WorkOrderState {
  if (mode === "paused") return "paused";
  if (mode === "operator") return "operator";
  if (mode === "stopped") return "stopped";
  return base;
}

function liveStages(wo: WorkOrderDetail, mode: RunMode): Record<LifecycleStage, StageStatus> {
  if (mode === "running" || mode === "static") return wo.stages;
  return { ...wo.stages, [wo.currentStage]: "paused" };
}

export function useLiveWorkOrder(id: string | undefined): LiveWorkOrder | undefined {
  const { state } = useCtx();
  if (!id) return undefined;
  const wo = WORK_ORDERS[id];
  const run = state.runs[id];
  if (!wo || !run) return undefined;
  return {
    ...wo,
    state: liveState(wo.state, run.mode),
    stages: liveStages(wo, run.mode),
    elapsedSec: run.elapsedSec,
    cost: { usd: run.costUsd },
    steps: run.steps,
    evidenceCount: run.evidenceCount,
    mode: run.mode,
    events: run.events,
    scriptIndex: run.scriptIndex,
  };
}

export function useRunControls(id: string) {
  const { dispatch } = useCtx();
  return useMemo(
    () => ({
      pause: () => dispatch({ type: "pause", id }),
      resume: () => dispatch({ type: "resume", id }),
      takeControl: () => dispatch({ type: "takeControl", id }),
      handBack: () => dispatch({ type: "handBack", id }),
      stop: () => dispatch({ type: "stop", id }),
    }),
    [dispatch, id],
  );
}

/** True while any WorkOrder is progressing autonomously. Drives the brand mark. */
export function useAnyRunning(): boolean {
  const { state } = useCtx();
  return Object.values(state.runs).some((r) => r.mode === "running");
}

export function usePalette() {
  const { state, dispatch } = useCtx();
  return {
    open: state.paletteOpen,
    setOpen: (open: boolean) => dispatch({ type: "palette", open }),
  };
}

export function useInspector() {
  const { state, dispatch } = useCtx();
  return {
    open: state.inspectorOpen,
    setOpen: (open: boolean) => dispatch({ type: "inspector", open }),
  };
}
