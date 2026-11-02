import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { sameOrigin } from "@/app/api/control/proxy";
import { STALE_MESSAGE } from "@/components/work-order/owner-commands";
import { WorkOrderView } from "@/components/work-order/work-order-view";
import contract from "@/data/__fixtures__/control-contract.json";
import { sendOwnerCommand, type CommandResult } from "@/data/control-source";
import type { Result, WorkOrderList, WorkOrderQuerySource } from "@/data/sources";
import { V2WorkOrderProvider } from "@/data/v2-provider";
import type { OwnerCommand, WorkOrderDetail } from "@/lib/types";

let pathname = "/work-orders/wo-1/execute";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));
const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

const WO1 = contract.detail["wo-1"] as unknown as WorkOrderDetail;
/** wo-1 as a freshly proposed plan, as the adapter reports it. */
const PROPOSED = {
  ...WO1,
  state: "plan_proposed",
  attention: undefined,
  commands: [
    { command: "approve_plan", enabled: true },
    { command: "reject_plan", enabled: true },
  ],
} as unknown as WorkOrderDetail;

function sourceOf(detail: WorkOrderDetail): WorkOrderQuerySource {
  return {
    getWorkOrder: async () => ({ status: "ready", data: detail }) as Result<WorkOrderDetail>,
    listWorkOrders: async () => ({ status: "ready", data: { active: [], attention: [], recent: [], unsupported: [] } }) as Result<WorkOrderList>,
  };
}

function renderWith(detail: WorkOrderDetail, stage: "execute" | "plan", result: CommandResult) {
  const send = vi.fn<(id: string, command: OwnerCommand, version: number, message?: string) => Promise<CommandResult>>(async () => result);
  render(
    <V2WorkOrderProvider source={sourceOf(detail)} openStream={null} ownerCommands send={send}>
      <WorkOrderView id="wo-1" stage={stage} />
    </V2WorkOrderProvider>,
  );
  return send;
}

describe("owner commands in control mode", () => {
  beforeEach(() => {
    toast.mockClear();
    toast.error.mockClear();
    pathname = "/work-orders/wo-1/execute";
  });

  it("records an attention decision on the version shown, with the owner's note", async () => {
    const send = renderWith(WO1, "execute", { status: "recorded", version: WO1.version! + 1 });
    await userEvent.click(await screen.findByRole("button", { name: "Abort" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent(`record v${WO1.version}`);
    await userEvent.type(screen.getByLabelText(/note for the record/i), "stale ticket");
    await userEvent.click(screen.getByRole("button", { name: "Abort" }));
    expect(send).toHaveBeenCalledWith("wo-1", "abort", WO1.version, "stale ticket");
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringMatching(/recorded on wo-1/)));
  });

  it("cancel sends nothing", async () => {
    const send = renderWith(WO1, "execute", { status: "recorded", version: 99 });
    await userEvent.click(await screen.findByRole("button", { name: "Defer" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(send).not.toHaveBeenCalled();
  });

  it("a stale version is reported, not retried", async () => {
    const send = renderWith(WO1, "execute", { status: "refused", error: "stale_version", message: "changed" });
    await userEvent.click(await screen.findByRole("button", { name: "Replan" }));
    await userEvent.click(screen.getByRole("button", { name: "Replan" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(STALE_MESSAGE));
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("an adapter-disabled command stays disabled even with an owner token", async () => {
    renderWith(WO1, "execute", { status: "recorded", version: 99 });
    const resume = await screen.findByRole("button", { name: "Resume" });
    expect(resume).toBeDisabled();
    expect(resume).toHaveAttribute("title", expect.stringMatching(/Workspace Broker/));
  });

  it("approves a proposed plan from the PLAN stage", async () => {
    pathname = "/work-orders/wo-1/plan";
    const send = renderWith(PROPOSED, "plan", { status: "recorded", version: WO1.version! + 1 });
    await userEvent.click(await screen.findByRole("button", { name: "Approve plan" }));
    await userEvent.click(screen.getByRole("button", { name: "Approve plan" }));
    expect(send).toHaveBeenCalledWith("wo-1", "approve_plan", WO1.version, "");
  });

  it("shows no command where none applies", async () => {
    pathname = "/work-orders/wo-2/execute";
    render(
      <V2WorkOrderProvider source={sourceOf(contract.detail["wo-2"] as unknown as WorkOrderDetail)} openStream={null} ownerCommands>
        <WorkOrderView id="wo-2" stage="execute" />
      </V2WorkOrderProvider>,
    );
    await screen.findByText("No executor runtime is connected to this WorkOrder.");
    expect(screen.queryByTestId("owner-commands")).not.toBeInTheDocument();
  });
});

describe("sendOwnerCommand", () => {
  it("posts only the command, the version seen and the note", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ workOrderId: "wo-1", version: 8, command: "defer" }))) as unknown as typeof fetch;
    const r = await sendOwnerCommand("wo-1", "defer", 7, "later", fetchImpl);
    expect(r).toEqual({ status: "recorded", version: 8 });
    const [url, init] = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/control/work-orders/wo-1/commands");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ command: "defer", expectedVersion: 7, message: "later" });
  });

  it("maps refusals to their error code and message", async () => {
    const body = { detail: { error: "stale_version", message: "changed" } };
    const fetchImpl = (async () => new Response(JSON.stringify(body), { status: 409 })) as typeof fetch;
    expect(await sendOwnerCommand("wo-1", "abort", 7, "", fetchImpl)).toEqual({ status: "refused", error: "stale_version", message: "changed" });
  });
});

describe("same-origin guard on the command route", () => {
  const req = (headers: Record<string, string>) => new Request("http://127.0.0.1:3000/api/control/work-orders/wo-1/commands", { method: "POST", headers });

  it("accepts this app's own pages", () => {
    expect(sameOrigin(req({ origin: "http://127.0.0.1:3000", host: "127.0.0.1:3000", "sec-fetch-site": "same-origin" }))).toBe(true);
  });

  it.each([
    ["no Origin", { host: "127.0.0.1:3000" }],
    ["another site", { origin: "https://evil.example", host: "127.0.0.1:3000" }],
    ["a cross-site fetch", { origin: "http://127.0.0.1:3000", host: "127.0.0.1:3000", "sec-fetch-site": "cross-site" }],
    ["a same-site but other-origin page", { origin: "http://127.0.0.1:3001", host: "127.0.0.1:3000", "sec-fetch-site": "same-site" }],
    ["a malformed Origin", { origin: "not a url", host: "127.0.0.1:3000" }],
  ])("refuses %s", (_what, headers) => {
    expect(sameOrigin(req(headers as Record<string, string>))).toBe(false);
  });
});

describe("deciding on what was shown", () => {
  it("sends the version shown when the dialog opened, even if the stream updated it", async () => {
    let version = WO1.version!;
    const source: WorkOrderQuerySource = {
      getWorkOrder: async () => ({ status: "ready", data: { ...WO1, version } }) as Result<WorkOrderDetail>,
      listWorkOrders: async () => ({ status: "ready", data: { active: [], attention: [], recent: [], unsupported: [] } }) as Result<WorkOrderList>,
    };
    const listeners = new Map<string, (ev: MessageEvent) => void>();
    const stream = {
      readyState: 1,
      onopen: null,
      onerror: null,
      addEventListener: (type: string, l: (ev: MessageEvent) => void) => listeners.set(type, l),
      close: () => {},
    };
    const send = vi.fn(async () => ({ status: "refused", error: "stale_version", message: "changed" }) as CommandResult);
    pathname = "/work-orders/wo-1/execute";
    render(
      <V2WorkOrderProvider source={source} openStream={() => stream} ownerCommands send={send}>
        <WorkOrderView id="wo-1" stage="execute" />
      </V2WorkOrderProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Abort" }));
    version += 1; // another writer moves the WorkOrder while the dialog is open
    listeners.get("work-order")!(new MessageEvent("work-order", { data: JSON.stringify({ workOrderId: "wo-1" }) }));
    expect(await screen.findByRole("status")).toHaveTextContent(`Changed to v${version}`);
    await userEvent.click(screen.getByRole("button", { name: "Abort" }));
    expect(send).toHaveBeenCalledWith("wo-1", "abort", WO1.version, "");
  });
});
