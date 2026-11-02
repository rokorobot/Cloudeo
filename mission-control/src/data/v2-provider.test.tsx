import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StatusBar } from "@/components/shell/status-bar";
import contract from "@/data/__fixtures__/control-contract.json";
import { useWorkOrderList, useWorkOrderResult } from "@/data/context";
import type { Result, WorkOrderList, WorkOrderQuerySource } from "@/data/sources";
import { V2WorkOrderProvider, type ControlStream } from "@/data/v2-provider";
import type { WorkOrderDetail } from "@/lib/types";

vi.mock("next/navigation", () => ({ usePathname: () => "/work-orders/wo-2/execute" }));

class FakeStream implements ControlStream {
  readyState = 0;
  onopen: ((ev: Event) => unknown) | null = null;
  onerror: ((ev: Event) => unknown) | null = null;
  closed = false;
  private listeners = new Map<string, ((ev: MessageEvent) => void)[]>();
  addEventListener(type: string, listener: (ev: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  open() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }
  emit(type: string, data: unknown) {
    for (const l of this.listeners.get(type) ?? []) l(new MessageEvent(type, { data: JSON.stringify(data) }));
  }
  fail(closed: boolean) {
    this.readyState = closed ? 2 : 0;
    this.onerror?.(new Event("error"));
  }
}

/** A source whose wo-2 version can be bumped, counting reads per key. */
function countingSource() {
  const reads = { list: 0, "wo-1": 0, "wo-2": 0 } as Record<string, number>;
  let version = contract.detail["wo-2"].version;
  const source: WorkOrderQuerySource = {
    getWorkOrder: async (id) => {
      reads[id] = (reads[id] ?? 0) + 1;
      const base = contract.detail[id as keyof typeof contract.detail];
      if (!base) return { status: "not_found" };
      const data = { ...base, version: id === "wo-2" ? version : base.version } as unknown as WorkOrderDetail;
      return { status: "ready", data } as Result<WorkOrderDetail>;
    },
    listWorkOrders: async () => {
      reads.list += 1;
      return { status: "ready", data: { active: [], attention: [], recent: [], unsupported: [] } } as Result<WorkOrderList>;
    },
  };
  return { source, reads, bump: () => (version += 1) };
}

function Probe({ id }: { id: string }) {
  useWorkOrderList();
  const r = useWorkOrderResult(id);
  return <div data-testid="version">{r.status === "ready" ? r.data.version : r.status}</div>;
}

function setup() {
  const streams: FakeStream[] = [];
  const counting = countingSource();
  const openStream = () => {
    const s = new FakeStream();
    streams.push(s);
    return s;
  };
  const view = render(
    <V2WorkOrderProvider source={counting.source} openStream={openStream} pollMs={60_000} reconnectMs={10}>
      <Probe id="wo-2" />
      <StatusBar />
    </V2WorkOrderProvider>,
  );
  return { ...counting, streams, view };
}

const flush = () => act(async () => {});
const link = () => screen.getByTestId("control-link").getAttribute("data-link");

describe("control mode realtime stream", () => {
  it("pushes a stored change to the open WorkOrder without polling", async () => {
    const { streams, bump, reads } = setup();
    expect(await screen.findByTestId("version")).toHaveTextContent(String(contract.detail["wo-2"].version));
    expect(link()).toBe("connecting");

    await act(async () => {
      streams[0].open();
      streams[0].emit("ready", { cursor: 7 });
    });
    expect(link()).toBe("live");
    const before = { ...reads };

    bump();
    await act(async () => streams[0].emit("work-order", { cursor: 8, workOrderId: "wo-2", version: 9, event: "x" }));
    expect(screen.getByTestId("version")).toHaveTextContent(String(contract.detail["wo-2"].version + 1));
    expect(reads["wo-2"]).toBe(before["wo-2"] + 1);
    expect(reads.list).toBe(before.list + 1);
  });

  it("ignores changes to WorkOrders nobody is showing", async () => {
    const { streams, reads } = setup();
    await act(async () => streams[0].open());
    const before = { ...reads };
    await act(async () => streams[0].emit("work-order", { cursor: 3, workOrderId: "wo-1", version: 2, event: "x" }));
    expect(reads["wo-1"]).toBe(0);
    expect(reads["wo-2"]).toBe(before["wo-2"]);
  });

  it("re-reads everything on ready (fresh subscribe or store reset)", async () => {
    const { streams, reads } = setup();
    await flush();
    const before = { ...reads };
    await act(async () => streams[0].emit("ready", { cursor: 0 }));
    expect(reads["wo-2"]).toBe(before["wo-2"] + 1);
    expect(reads.list).toBe(before.list + 1);
  });

  it("does not lose a change that lands while a read is in flight", async () => {
    let release: () => void = () => {};
    let version = 1;
    const reads: number[] = [];
    const source: WorkOrderQuerySource = {
      getWorkOrder: async () => {
        const seen = version;
        reads.push(seen);
        if (reads.length === 2) await new Promise<void>((r) => (release = r));
        return { status: "ready", data: { ...contract.detail["wo-2"], version: seen } as unknown as WorkOrderDetail };
      },
      listWorkOrders: async () => ({ status: "ready", data: { active: [], attention: [], recent: [], unsupported: [] } }),
    };
    const streams: FakeStream[] = [];
    render(
      <V2WorkOrderProvider source={source} openStream={() => (streams.push(new FakeStream()), streams.at(-1)!)} pollMs={60_000}>
        <Probe id="wo-2" />
      </V2WorkOrderProvider>,
    );
    await flush();
    version = 2;
    await act(async () => streams[0].emit("work-order", { cursor: 1, workOrderId: "wo-2", version: 2, event: "x" }));
    version = 3; // lands while the read of v2 is still in flight
    await act(async () => streams[0].emit("work-order", { cursor: 2, workOrderId: "wo-2", version: 3, event: "x" }));
    await act(async () => release());
    expect(screen.getByTestId("version")).toHaveTextContent("3");
    expect(reads).toEqual([1, 2, 3]);
  });

  it("falls back and reconnects after the stream is refused", async () => {
    const { streams } = setup();
    await act(async () => streams[0].open());
    expect(link()).toBe("live");
    await act(async () => streams[0].fail(true));
    expect(link()).toBe("polling");
    await act(() => new Promise((r) => setTimeout(r, 30)));
    expect(streams).toHaveLength(2);
    await act(async () => streams[1].open());
    expect(link()).toBe("live");
  });

  it("leaves network drops to EventSource's own retry", async () => {
    const { streams } = setup();
    await act(async () => streams[0].fail(false));
    await act(() => new Promise((r) => setTimeout(r, 30)));
    expect(streams).toHaveLength(1);
    expect(link()).toBe("polling");
  });

  it("closes the stream on unmount", async () => {
    const { streams, view } = setup();
    await flush();
    view.unmount();
    expect(streams[0].closed).toBe(true);
  });
});
