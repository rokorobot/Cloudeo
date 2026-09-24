import { describe, expect, it } from "vitest";

import { initialState, reducer } from "@/state/mission-control";

const ID = "WO-1842";
const run = (s: ReturnType<typeof initialState>) => s.runs[ID];

describe("run simulation reducer", () => {
  it("starts WO-1842 running and WO-1845 static", () => {
    const s = initialState();
    expect(run(s).mode).toBe("running");
    expect(s.runs["WO-1845"].mode).toBe("static");
  });

  it("advances the script only while running", () => {
    let s = reducer(initialState(), { type: "step", id: ID });
    expect(run(s).steps).toBe(19);
    expect(run(s).events.at(-1)?.text).toBe("Opened vendor portal");

    s = reducer(s, { type: "pause", id: ID });
    const paused = reducer(s, { type: "step", id: ID });
    expect(paused).toBe(s);
  });

  it("pauses and resumes, recording both in the feed", () => {
    let s = reducer(initialState(), { type: "pause", id: ID });
    expect(run(s).mode).toBe("paused");
    expect(run(s).events.at(-1)?.text).toBe("Paused by operator");

    s = reducer(s, { type: "resume", id: ID });
    expect(run(s).mode).toBe("running");
    expect(run(s).events.at(-1)?.text).toBe("Resumed");
  });

  it("take control stops autonomous steps and appends an operator event", () => {
    let s = reducer(initialState(), { type: "takeControl", id: ID });
    expect(run(s).mode).toBe("operator");
    expect(run(s).events.at(-1)).toMatchObject({ kind: "operator", text: "Operator took control" });
    expect(reducer(s, { type: "step", id: ID })).toBe(s);
    // Pause/resume do not apply while the operator holds the browser.
    expect(reducer(s, { type: "resume", id: ID })).toBe(s);

    s = reducer(s, { type: "handBack", id: ID });
    expect(run(s).mode).toBe("running");
    expect(run(s).events.at(-1)?.kind).toBe("operator");
  });

  it("stop is terminal", () => {
    const s = reducer(initialState(), { type: "stop", id: ID });
    expect(run(s).mode).toBe("stopped");
    for (const type of ["resume", "takeControl", "step", "stop"] as const) {
      expect(reducer(s, { type, id: ID })).toBe(s);
    }
  });

  it("ticks the clock for running and operator-held runs only", () => {
    const start = run(initialState()).elapsedSec;
    expect(run(reducer(initialState(), { type: "tick" })).elapsedSec).toBe(start + 1);
    const paused = reducer(initialState(), { type: "pause", id: ID });
    expect(run(reducer(paused, { type: "tick" })).elapsedSec).toBe(start);
    expect(reducer(paused, { type: "tick" }).runs["WO-1845"]).toBe(paused.runs["WO-1845"]);
  });
});
