import { describe, expect, it } from "vitest";

import contract from "@/data/__fixtures__/control-contract.json";
import { HttpWorkOrderQuerySource } from "@/data/control-source";
import { dataSourceFromEnv } from "@/data/mode";

function sourceReturning(status: number, body: unknown) {
  const fetchImpl = (async () => new Response(JSON.stringify(body), { status })) as typeof fetch;
  return new HttpWorkOrderQuerySource("/api/control", fetchImpl);
}

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const WO1 = contract.detail["wo-1"];

describe("control source reads the adapter contract", () => {
  it("accepts the real adapter output", async () => {
    const r = await sourceReturning(200, WO1).getWorkOrder("wo-1");
    expect(r.status).toBe("ready");
    if (r.status === "ready") {
      expect(r.data.state).toBe("attention");
      expect(r.data.execution?.runtime).toBe("unavailable");
    }
  });

  it("groups the real list into attention and active", async () => {
    const r = await sourceReturning(200, contract.list).listWorkOrders();
    expect(r.status).toBe("ready");
    if (r.status === "ready") {
      expect(r.data.attention.map((w) => w.id)).toEqual(["wo-1"]);
      expect(r.data.active.map((w) => w.id)).toEqual(["wo-2"]);
      expect(r.data.unsupported).toEqual([]);
    }
  });
});

describe("control source fails closed", () => {
  it.each([
    ["an unknown WorkOrder state", (d: typeof WO1) => void (d.state = "SOMETHING_NEW")],
    ["a demo-only state", (d: typeof WO1) => void (d.state = "operator")],
    ["an unknown stage status", (d: typeof WO1) => void ((d.stages as Record<string, string>).execute = "sleeping")],
    ["an unknown checkpoint status", (d: typeof WO1) => void ((d.checkpoints.items[0] as { status: string }).status = "maybe")],
    ["an unknown history state", (d: typeof WO1) => void (d.history[0].state = "SOMETHING_NEW")],
    ["a non-control source", (d: typeof WO1) => void ((d as { source: string }).source = "fixture")],
  ])("rejects %s as unsupported", async (_what, mutate) => {
    const body = clone(WO1);
    mutate(body);
    const r = await sourceReturning(200, body).getWorkOrder("wo-1");
    expect(r).toMatchObject({ status: "error", kind: "unsupported" });
  });

  it("keeps unsupported list entries visible", async () => {
    const list = clone(contract.list);
    list.workOrders[1].state = "SOMETHING_NEW";
    list.workOrders.push({ id: "wo-3", unsupported: "does not load", source: "control" } as never);
    const r = await sourceReturning(200, list).listWorkOrders();
    expect(r.status).toBe("ready");
    if (r.status === "ready") {
      expect(r.data.unsupported.map((u) => u.id)).toEqual(["wo-2", "wo-3"]);
      expect(r.data.active).toEqual([]);
    }
  });

  it.each([
    [404, { status: "not_found" }],
    [422, { status: "error", kind: "unsupported" }],
    [503, { status: "error", kind: "unavailable" }],
    [500, { status: "error", kind: "failed" }],
  ])("maps HTTP %i explicitly", async (status, expected) => {
    const r = await sourceReturning(status, { detail: { error: "x", message: "m" } }).getWorkOrder("wo-1");
    expect(r).toMatchObject(expected);
  });

  it("reports an unreachable API as unavailable", async () => {
    const failing = new HttpWorkOrderQuerySource("/api/control", (async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch);
    expect(await failing.listWorkOrders()).toMatchObject({ status: "error", kind: "unavailable" });
  });
});

describe("mode selection", () => {
  it("defaults to demo and rejects unknown values", () => {
    expect(dataSourceFromEnv(undefined)).toBe("fixture");
    expect(dataSourceFromEnv("demo")).toBe("fixture");
    expect(dataSourceFromEnv("control")).toBe("control");
    expect(() => dataSourceFromEnv("prod")).toThrow(/MISSION_CONTROL_SOURCE/);
  });
});
