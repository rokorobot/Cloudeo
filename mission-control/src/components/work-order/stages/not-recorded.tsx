import { Panel, SectionLabel } from "@/components/common/status";
import type { LifecycleStage } from "@/lib/types";
import type { LiveWorkOrder } from "@/state/mission-control";

/** A completed stage whose detail is not part of the fixture set. */
export function NotRecorded({ stage, wo }: { stage: LifecycleStage; wo: LiveWorkOrder }) {
  const done = wo.stages[stage] === "done";
  return (
    <Panel className="flex flex-col items-start gap-2 p-5">
      <SectionLabel>{stage} · {done ? "done" : "not reached"}</SectionLabel>
      <p className="max-w-[62ch] text-subtle">
        {done
          ? `All ${wo.blocks?.total ?? ""} blocks passed audit and were checkpointed. Per-block detail for ${wo.id} is not included in these fixtures; see the checkpoint chain for the accepted state.`
          : "This stage has not been reached yet."}
      </p>
    </Panel>
  );
}
