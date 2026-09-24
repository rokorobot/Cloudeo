import { Chip, Panel, PanelFooter, PanelHeader, SectionLabel } from "@/components/common/status";
import { formatDuration, formatMoney, formatPercent } from "@/lib/format";
import type { MemoryView } from "@/lib/types";
import { cn } from "@/lib/utils";

export function MemoryStage({ memory }: { memory: MemoryView }) {
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
