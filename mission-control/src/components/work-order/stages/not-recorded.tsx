import { Panel, SectionLabel } from "@/components/common/status";
import type { LifecycleStage } from "@/lib/types";
import type { LiveWorkOrder } from "@/data/sources";

/** A stage with no recorded detail: not reached yet, or (demo) not in the fixtures. */
export function NotRecorded({ stage, wo }: { stage: LifecycleStage; wo: LiveWorkOrder }) {
  const done = wo.stages[stage] === "done";
  return (
    <Panel className="flex flex-col items-start gap-2 p-5">
      <SectionLabel>{stage} · {done ? "done" : "not reached"}</SectionLabel>
      <p className="max-w-[62ch] text-subtle">
        {done && wo.source === "control"
          ? "Nothing is recorded for this stage in the control store."
          : done
          ? `All ${wo.blocks?.total ?? ""} blocks passed audit and were checkpointed. Per-block detail for ${wo.id} is not included in these fixtures; see the checkpoint chain for the accepted state.`
          : "This stage has not been reached yet."}
      </p>
    </Panel>
  );
}
