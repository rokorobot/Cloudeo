import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LifecycleBar } from "@/components/work-order/lifecycle-bar";
import { WORK_ORDERS } from "@/fixtures/work-orders";
import { LIFECYCLE } from "@/lib/types";

describe("LifecycleBar", () => {
  it("links every stage to its own route and marks the selected one", () => {
    const wo = WORK_ORDERS["WO-1842"];
    render(<LifecycleBar id={wo.id} stages={wo.stages} selected="audit" />);

    const links = screen.getAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual(LIFECYCLE.map((s) => `/work-orders/WO-1842/${s}`));

    const current = links.filter((l) => l.getAttribute("aria-current") === "step");
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent(/audit/i);
  });

  it("shows stage status from the WorkOrder, not from selection", () => {
    const wo = WORK_ORDERS["WO-1845"];
    render(<LifecycleBar id={wo.id} stages={wo.stages} selected="plan" />);
    expect(screen.getByRole("link", { name: /verify/i })).toHaveTextContent(/attention/i);
    expect(screen.getByRole("link", { name: /promote/i })).toHaveTextContent("—");
  });
});
