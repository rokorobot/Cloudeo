"use client";

import { useCallback, useEffect, useMemo, useReducer, type ReactNode } from "react";

import { WorkOrderDataContext, type WorkOrderData } from "@/data/context";
import type { LiveWorkOrder, Result, RunMode, WorkOrderCommandSource, WorkOrderList } from "@/data/sources";
import { HEALTH } from "@/fixtures/health";
import { ACTIVE, ATTENTION, RECENT, WORK_ORDERS } from "@/fixtures/work-orders";
import type { ActivityEvent, LifecycleStage, StageStatus, WorkOrderDetail, WorkOrderState } from "@/lib/types";

/**
 * Demo backend: fixtures plus a client-side simulation of live progress.
 * The only source whose WorkOrders accept commands (pause, take control, ...).
 */

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

export interface SimState {
  runs: Record<string, LiveRun>;
}

type RunAction = "step" | "pause" | "resume" | "takeControl" | "handBack" | "stop";
type Action = { type: "tick" } | { type: RunAction; id: string };

const MAX_EVENTS = 40;
const STEP_COST_USD = 0.02;

export function initialState(): SimState {
  const runs: Record<string, LiveRun> = {};
  for (const wo of Object.values(WORK_ORDERS)) {
    const live = !!wo.execution && wo.state === "executing";
    runs[wo.id] = {
      mode: live ? "running" : "static",
      elapsedSec: wo.elapsedSec ?? 0,
      costUsd: wo.cost?.usd ?? 0,
      steps: wo.steps ?? 0,
      evidenceCount: wo.evidenceCount,
      events: wo.execution?.seedEvents ?? [],
      scriptIndex: 0,
      eventSeq: 0,
    };
  }
  return { runs };
}

function withEvent(run: LiveRun, e: Omit<ActivityEvent, "id" | "atSec">): LiveRun {
  const event: ActivityEvent = { ...e, id: `e${run.eventSeq}`, atSec: run.elapsedSec };
  return { ...run, eventSeq: run.eventSeq + 1, events: [...run.events, event].slice(-MAX_EVENTS) };
}

export function reducer(state: SimState, action: Action): SimState {
  if (action.type === "tick") {
    let changed = false;
    const runs = { ...state.runs };
    for (const [id, run] of Object.entries(runs)) {
      if (run.mode === "running" || run.mode === "operator") {
        runs[id] = { ...run, elapsedSec: run.elapsedSec + 1 };
        changed = true;
      }
    }
    return changed ? { runs } : state;
  }

  const run = state.runs[action.id];
  if (!run) return state;
  const set = (next: LiveRun): SimState => ({ runs: { ...state.runs, [action.id]: next } });

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

function toLive(wo: WorkOrderDetail, run: LiveRun): LiveWorkOrder {
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

const LIST: Result<WorkOrderList> = {
  status: "ready",
  data: { active: ACTIVE, attention: ATTENTION, recent: RECENT, unsupported: [] },
};

export function FixtureWorkOrderProvider({ children }: { children: ReactNode }) {
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

  const subscribe = useCallback(() => () => {}, []);

  const value = useMemo<WorkOrderData>(() => {
    const commands = (id: string): WorkOrderCommandSource | null => {
      if (!WORK_ORDERS[id]?.execution || !state.runs[id]) return null;
      return {
        pause: () => dispatch({ type: "pause", id }),
        resume: () => dispatch({ type: "resume", id }),
        stop: () => dispatch({ type: "stop", id }),
        takeControl: () => dispatch({ type: "takeControl", id }),
        handBack: () => dispatch({ type: "handBack", id }),
      };
    };
    return {
      source: "fixture",
      readWorkOrder: (id) => {
        const wo = WORK_ORDERS[id.toUpperCase()];
        const run = wo && state.runs[wo.id];
        return wo && run ? { status: "ready", data: toLive(wo, run) } : { status: "not_found" };
      },
      readList: () => LIST,
      subscribe,
      commands,
      health: HEALTH,
      anyRunning: Object.values(state.runs).some((r) => r.mode === "running"),
    };
  }, [state, subscribe]);

  return <WorkOrderDataContext.Provider value={value}>{children}</WorkOrderDataContext.Provider>;
}
