import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AttentionPanel } from "@/components/work-order/stages/attention-panel";
import { WORK_ORDERS } from "@/fixtures/work-orders";
import type { LiveWorkOrder } from "@/data/sources";

const base = WORK_ORDERS["WO-1845"];
const wo: LiveWorkOrder = { ...base, mode: "static", events: [], scriptIndex: 0 };

describe("INDEPENDENCE_UNAVAILABLE attention", () => {
  it("states that policy was not weakened and offers the normal recovery paths first", () => {
    render(<AttentionPanel wo={wo} attention={base.attention!} />);
    expect(screen.getByText("No policy was weakened.")).toBeInTheDocument();

    const labels = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    const wait = labels.findIndex((t) => t.includes("Wait for an eligible independent provider"));
    const add = labels.findIndex((t) => t.includes("Add or configure an eligible provider"));
    const override = labels.findIndex((t) => t.includes("Owner policy override"));
    expect(wait).toBeGreaterThanOrEqual(0);
    expect(wait).toBeLessThan(add);
    expect(add).toBeLessThan(override);
    expect(screen.queryByText(/verify it yourself/i)).not.toBeInTheDocument();
  });

  it("guards the owner override behind a reason and an acknowledgement", async () => {
    const user = userEvent.setup();
    render(<AttentionPanel wo={wo} attention={base.attention!} />);

    await user.click(screen.getByRole("button", { name: /owner policy override/i }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("envelope.final_verifier.independence");
    expect(dialog).toHaveTextContent(/recorded as a policy amendment/i);

    const submit = screen.getByRole("button", { name: /submit amendment for approval/i });
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText(/reason for the override/i), "too short");
    await user.click(screen.getByRole("checkbox"));
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText(/reason for the override/i), " — release freeze approved by owner");
    expect(submit).toBeEnabled();

    await user.click(screen.getByRole("checkbox"));
    expect(submit).toBeDisabled();
  });
});
