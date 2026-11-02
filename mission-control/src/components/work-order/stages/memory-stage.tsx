import { Chip, Panel, PanelFooter, PanelHeader, SectionLabel } from "@/components/common/status";
import { formatDuration, formatMoney, formatPercent } from "@/lib/format";
import type { LiveWorkOrder } from "@/data/sources";
import type { MemoryCurationView, MemoryView } from "@/lib/types";
import { cn } from "@/lib/utils";

const CURATION_LABEL: Record<MemoryCurationView["status"], string> = {
  not_started: "NOT STARTED",
  curating: "CURATING",
  auditing: "MEMORY AUDIT",
  approved: "APPROVED",
};

/** V2 MEMORY stage: memory curation per block, approved by an independent Memory Audit. */
function MemoryCuration({ items }: { items: MemoryCurationView[] }) {
  return (
    <Panel>
      <PanelHeader>
        <SectionLabel>Memory curation</SectionLabel>
      </PanelHeader>
      {items.length === 0 ? (
        <p className="p-3.5 text-subtle">No block in the approved plan has memory impact, so this stage does not apply.</p>
      ) : (
        <ul className="flex flex-col">
          {items.map((m) => (
            <li key={m.blockId} className="flex flex-col gap-1.5 border-b border-line-soft px-3.5 py-3 last:border-b-0">
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="font-mono text-[12px] text-muted-foreground">{m.blockId}</span>
                <span className="flex-1">{m.blockTitle}</span>
                <Chip tone={m.status === "approved" ? "ok" : m.status === "not_started" ? "neutral" : "brand"}>{CURATION_LABEL[m.status]}</Chip>
              </div>
              {m.changedPaths.length > 0 && (
                <span className="font-mono text-[11.5px] text-subtle">changed {m.changedPaths.join(", ")}</span>
              )}
              {m.outsidePaths.length > 0 && (
                <span className="font-mono text-[11.5px] text-warn">outside memory_paths: {m.outsidePaths.join(", ")}</span>
              )}
              {m.auditor && (
                <span className="text-[12px] text-muted-foreground">
                  Memory Audit {m.auditStatus} by <span className="font-mono">{m.auditor}</span>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      <PanelFooter>
        <span className="text-[12px] text-muted-foreground">
          Performance memory (verified outcomes per profile) is not recorded by the V2 control store yet.
        </span>
      </PanelFooter>
    </Panel>
  );
}

export function MemoryStage({ wo }: { wo: LiveWorkOrder }) {
  if (wo.memoryCuration) return <MemoryCuration items={wo.memoryCuration} />;
  if (wo.memory) return <PerformanceMemory memory={wo.memory} />;
  return (
    <Panel className="p-5">
      <p className="text-subtle">Nothing is recorded for this stage.</p>
    </Panel>
  );
}

function PerformanceMemory({ memory }: { memory: MemoryView }) {
  return (
    <Panel>
      <PanelHeader>
        <SectionLabel>Performance memory</SectionLabel>
        <Chip>OBSERVED</Chip>
        <span className="flex-1" />
        <span className="font-mono text-[11.5px] text-muted-foreground">
          {memory.taskClass} · {memory.window}
        </span>
      </PanelHeader>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px]">
          <thead>
            <tr className="border-b border-line-soft">
              <th className="label-caps px-3.5 py-2 text-left">Profile</th>
              <th className="label-caps px-3.5 py-2 text-left">Verified successes</th>
              <th className="label-caps px-3.5 py-2 text-right">Median time</th>
              <th className="label-caps px-3.5 py-2 text-right">p95 time</th>
              <th className="label-caps px-3.5 py-2 text-right">Median cost</th>
              <th className="label-caps px-3.5 py-2 text-left">Evidence basis</th>
            </tr>
          </thead>
          <tbody className="font-mono text-[12px]">
            {memory.rows.map((r) => {
              const o = r.observed;
              const pct = (o.verifiedSuccesses / o.attempts) * 100;
              return (
                <tr key={r.profileId} className={cn("border-b border-line-soft last:border-b-0", r.selected && "bg-brand/[0.08]")}>
                  <td className="px-3.5 py-2.5">
                    {r.profileId}
                    {r.selected && <span className="ml-2 font-sans text-[11px] text-brand">in use</span>}
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className="flex items-center gap-2.5 tnum">
                      <span className="inline-block h-[5px] w-24 overflow-hidden rounded bg-line" aria-hidden>
                        <i className="block h-full bg-subtle/60" style={{ width: `${pct}%` }} />
                      </span>
                      {o.verifiedSuccesses} of {o.attempts}
                      <span className="text-muted-foreground">({formatPercent(o.verifiedSuccesses, o.attempts)})</span>
                    </span>
                  </td>
                  <td className="px-3.5 py-2.5 text-right tnum">{formatDuration(o.medianSec)}</td>
                  <td className="px-3.5 py-2.5 text-right tnum">{formatDuration(r.p95Sec)}</td>
                  <td className="px-3.5 py-2.5 text-right tnum">{formatMoney(o.medianCost)}</td>
                  <td className="px-3.5 py-2.5 font-sans text-[12px] text-subtle">{r.evidenceBasis}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <PanelFooter className="flex-col items-start gap-1">
        <span className="text-[12.5px] text-subtle">
          These are counts of past outcomes that passed independent verification. They are not predictions for this WorkOrder.
        </span>
        <span className="text-[12px] text-muted-foreground">
          Memory is written only after verification. This WorkOrder adds one observation per audited block.
        </span>
      </PanelFooter>
    </Panel>
  );
}
