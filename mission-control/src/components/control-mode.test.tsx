import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Inspector } from "@/components/shell/inspector";
import { WorkOrderView } from "@/components/work-order/work-order-view";
import contract from "@/data/__fixtures__/control-contract.json";
import type { Result, WorkOrderList, WorkOrderQuerySource } from "@/data/sources";
import { V2WorkOrderProvider } from "@/data/v2-provider";
import type { WorkOrderDetail } from "@/lib/types";

let pathname = "/work-orders/wo-1/execute";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

/** Serves the real adapter contract, as the HTTP source would after parsing. */
const source: WorkOrderQuerySource = {
  getWorkOrder: async (id) =>
    (id in contract.detail
      ? { status: "ready", data: contract.detail[id as keyof typeof contract.detail] as unknown as WorkOrderDetail }
      : { status: "not_found" }) as Result<WorkOrderDetail>,
  listWorkOrders: async () =>
    ({
      status: "ready",
      data: { active: [], attention: [], recent: [], unsupported: [] },
    }) as Result<WorkOrderList>,
};

function renderControl(ui: React.ReactNode) {
  return render(<V2WorkOrderProvider source={source}>{ui}</V2WorkOrderProvider>);
}

describe("control mode (read-only V2 WorkOrders)", () => {
  beforeEach(() => {
    pathname = "/work-orders/wo-2/execute";
  });

  it("EXECUTE shows no simulated runtime next to a real WorkOrder", async () => {
    renderControl(<WorkOrderView id="wo-2" stage="execute" />);
    expect(await screen.findByText("No executor runtime is connected to this WorkOrder.")).toBeInTheDocument();
    expect(screen.getByText("Runtime telemetry").nextElementSibling).toHaveTextContent("unavailable");
    expect(screen.getByText("Control state").nextElementSibling).toHaveTextContent("EXECUTING");
    expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /take control/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/agent activity/i)).not.toBeInTheDocument();
    // The header carries no elapsed time or cost: the control store records neither.
    const header = screen.getByRole("banner");
    expect(within(header).queryByText("Elapsed")).not.toBeInTheDocument();
    expect(within(header).queryByText("Cost")).not.toBeInTheDocument();
    expect(within(header).getByText(new RegExp(`record v${contract.detail["wo-2"].version}`))).toBeInTheDocument();
  });

  it("Inspector disables every command and marks missing telemetry", async () => {
    renderControl(<Inspector />);
    await screen.findByText("EXECUTING");
    expect(screen.getByRole("button", { name: /pause/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /stop/i })).toBeDisabled();
    expect(screen.getByText("Control actions not connected yet")).toBeInTheDocument();
    const costRow = screen.getByText("Cost").nextElementSibling;
    expect(costRow).toHaveTextContent("not recorded");
    expect(screen.getByText("Elapsed").nextElementSibling).toHaveTextContent("not recorded");
  });

  it("a candidate checkpoint is never rendered as accepted", async () => {
    renderControl(<WorkOrderView id="wo-2" stage="checkpoint" />);
    const chain = await screen.findByRole("list", { name: "Checkpoints" });
    const items = within(chain).getAllByRole("listitem");
    expect(items.map((i) => i.dataset.status)).toEqual(["baseline", "candidate"]);
    expect(within(chain).queryByText("ACCEPTED")).not.toBeInTheDocument();
    expect(within(chain).getByText("CANDIDATE · NOT ACCEPTED")).toBeInTheDocument();
    expect(within(chain).getByText("no commit yet")).toBeInTheDocument();
  });

  it("attention shows the recorded reasons and offers no working actions", async () => {
    pathname = "/work-orders/wo-1/execute";
    renderControl(<WorkOrderView id="wo-1" stage="execute" />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("INDEPENDENCE_UNAVAILABLE");
    expect(alert).toHaveTextContent("No reason has been waived.");
    for (const action of ["resume", "change_agent", "abort"]) {
      expect(screen.getByRole("button", { name: action })).toBeDisabled();
    }
    expect(screen.queryByText(/owner policy override/i)).not.toBeInTheDocument();
  });

  it("a WorkOrder missing from the control store is reported, not invented", async () => {
    renderControl(<WorkOrderView id="wo-404" stage="plan" />);
    expect(await screen.findByText(/No WorkOrder with this ID exists/)).toBeInTheDocument();
  });
});
