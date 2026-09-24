import { Chip, Panel, PanelHeader, SectionLabel } from "@/components/common/status";
import type { LiveWorkOrder } from "@/data/sources";
import { formatDuration, formatMoney, formatPercent, formatTimestamp } from "@/lib/format";
import type { PlanView, RoutingCandidate } from "@/lib/types";
import { cn } from "@/lib/utils";

const CRITERION_MARK = {
  met: <span className="text-ok">✓</span>,
  in_progress: <span className="text-brand">●</span>,
  pending: <span className="text-muted-foreground">○</span>,
  unassessed: <span className="text-muted-foreground">·</span>,
};

function CandidateRow({ c }: { c: RoutingCandidate }) {
  const filtered = c.status === "filtered";
  const o = c.observed;
  return (
    <tr className={cn("border-b border-line-soft last:border-b-0", c.status === "selected" && "bg-brand/[0.08]")}>
      <td className="px-3.5 py-2.5 align-top">
        <div className={cn("flex flex-col gap-0.5", filtered && "text-muted-foreground")}>
          <span className="font-mono text-[12px]">{c.profileId}</span>
          <span className="text-[12px] text-muted-foreground">{c.label}</span>
        </div>
      </td>
      <td className="px-3.5 py-2.5 align-top">
        {c.status === "selected" && <Chip tone="brand">SELECTED</Chip>}
        {c.status === "eligible" && <Chip>ELIGIBLE</Chip>}
        {filtered && <Chip className="text-muted-foreground">FILTERED</Chip>}
      </td>
      {filtered ? (
        <td colSpan={4} className="px-3.5 py-2.5 align-top text-[12.5px] text-subtle">
          {c.filterReason}
        </td>
      ) : (
        <>
          <td className="px-3.5 py-2.5 text-right align-top font-mono text-[12px] tnum">
            {o ? (
              <span className="flex flex-col items-end gap-0.5">
                <span>{formatPercent(o.verifiedSuccesses, o.attempts)}</span>
                <span className="text-[11px] text-muted-foreground">{o.verifiedSuccesses} of {o.attempts}</span>
              </span>
            ) : "—"}
          </td>
          <td className="px-3.5 py-2.5 text-right align-top font-mono text-[12px] tnum">{o ? formatDuration(o.medianSec) : "—"}</td>
          <td className="px-3.5 py-2.5 text-right align-top font-mono text-[12px] tnum">{o ? formatMoney(o.medianCost) : "—"}</td>
          <td className="px-3.5 py-2.5 text-right align-top font-mono text-[12px] tnum">{c.policyScore?.toFixed(2) ?? "—"}</td>
        </>
      )}
    </tr>
  );
}

function CriteriaCount({ plan }: { plan: PlanView }) {
  const total = plan.acceptanceCriteria.length;
  if (plan.acceptanceCriteria.every((c) => c.status === "unassessed")) return <>{total} recorded · not assessed until VERIFY</>;
  return <>{plan.acceptanceCriteria.filter((c) => c.status === "met").length} of {total} met</>;
}

function Routing({ plan }: { plan: PlanView }) {
  const r = plan.routing;
  if (!r) return null;
  return (
    <Panel>
      <PanelHeader>
        <SectionLabel>Routing decision</SectionLabel>
        <span className="flex-1" />
        <span className="font-mono text-[11.5px] text-muted-foreground">
          {r.policy} · {r.decidedAt}
        </span>
      </PanelHeader>
      <p className="max-w-[80ch] px-3.5 pt-3 text-subtle">{r.rationale}</p>
      <div className="flex flex-wrap items-center gap-2 px-3.5 pt-3 pb-1">
        <SectionLabel className="mr-1">Hard constraints</SectionLabel>
        {r.hardConstraints.map((h) => <Chip key={h}>{h}</Chip>)}
      </div>
      <div className="overflow-x-auto">
        <table className="mt-2 w-full min-w-[640px] border-t border-line-soft">
          <caption className="caption-bottom border-t border-line-soft px-3.5 py-2.5 text-left text-[12px] text-muted-foreground">
            Observed = independently verified outcomes on this task class over the {r.candidates.find((c) => c.observed)?.observed?.window ?? "recent window"}.
            These are past results, not a forecast for this run. The policy score is the router&apos;s ranking, not a probability of success.
          </caption>
          <thead>
            <tr className="border-b border-line-soft">
              <th className="label-caps px-3.5 py-2 text-left">Profile</th>
              <th className="label-caps px-3.5 py-2 text-left">Decision</th>
              <th className="label-caps px-3.5 py-2 text-right">Observed verified</th>
              <th className="label-caps px-3.5 py-2 text-right">Median time</th>
              <th className="label-caps px-3.5 py-2 text-right">Median cost</th>
              <th className="label-caps px-3.5 py-2 text-right">Policy score</th>
            </tr>
          </thead>
          <tbody>
            {r.candidates.map((c) => <CandidateRow key={c.profileId} c={c} />)}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

/** The approved (or proposed) plan and the profile snapshot, as stored in V2. */
function ControlPlan({ plan }: { plan: PlanView }) {
  if (plan.planVersion === undefined && !plan.bindings?.length) return null;
  return (
    <div className="grid gap-3.5 xl:grid-cols-[1.2fr_1fr]">
      <Panel>
        <PanelHeader>
          <SectionLabel>{plan.planVersion ? `Plan v${plan.planVersion}` : "Plan"}</SectionLabel>
          <Chip tone={plan.approval ? "brand" : "neutral"}>{plan.approval ? "APPROVED" : plan.planVersion ? "PROPOSED" : "NO PLAN YET"}</Chip>
          <span className="flex-1" />
          {plan.approval && (
            <span className="font-mono text-[11.5px] text-muted-foreground">
              {plan.approval.approvedBy} · {formatTimestamp(plan.approval.approvedAt)} · profile v{plan.approval.profileVersion}
            </span>
          )}
        </PanelHeader>
        {plan.architectureSummary && <p className="max-w-[80ch] px-3.5 pt-3 text-subtle">{plan.architectureSummary}</p>}
        <ol className="flex flex-col gap-2.5 p-3.5">
          {(plan.blocks ?? []).map((b) => (
            <li key={b.id} className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
              <span className="font-mono text-[11.5px] text-muted-foreground">{String(b.order).padStart(2, "0")}</span>
              <span>
                {b.goal} <span className="ml-1 font-mono text-[11px] text-muted-foreground">{b.id}</span>
                {b.memoryImpact && <Chip className="ml-2">MEMORY IMPACT</Chip>}
              </span>
              <span className="col-start-2 font-mono text-[11.5px] text-muted-foreground">
                scope {b.scope.join(", ")} · checks {b.acceptanceChecks.join("; ")}
              </span>
            </li>
          ))}
        </ol>
      </Panel>
      {!!plan.bindings?.length && (
        <Panel>
          <PanelHeader>
            <SectionLabel>Execution profile bindings</SectionLabel>
          </PanelHeader>
          <table className="w-full text-[12.5px]">
            <tbody>
              {plan.bindings.map((b) => (
                <tr key={b.role} className="border-b border-line-soft last:border-b-0">
                  <td className="px-3.5 py-2 align-top font-mono text-[12px]">{b.role}</td>
                  <td className="px-3.5 py-2 align-top">
                    <span className="font-mono text-[12px]">{b.primary}</span>
                    {b.fallbacks.length > 0 && (
                      <span className="block text-[11.5px] text-muted-foreground">
                        fallback {b.fallbacks.join(", ")} on {b.fallbackConditions.join(", ")}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </div>
  );
}

export function PlanStage({ wo, plan }: { wo: LiveWorkOrder; plan: PlanView }) {
  return (
    <>
      <div className="grid gap-3.5 xl:grid-cols-[1fr_1fr]">
        <Panel>
          <PanelHeader><SectionLabel>Objective</SectionLabel></PanelHeader>
          <p className="max-w-[65ch] p-3.5 text-subtle">{wo.objective}</p>
        </Panel>
        <Panel>
          <PanelHeader>
            <SectionLabel>Acceptance criteria</SectionLabel>
            <span className="flex-1" />
            <span className="font-mono text-[11.5px] text-muted-foreground">
              <CriteriaCount plan={plan} />
            </span>
          </PanelHeader>
          {plan.acceptanceCriteria.length === 0 ? (
            <p className="p-3.5 text-muted-foreground">No plan has been proposed yet.</p>
          ) : (
            <ul className="flex flex-col gap-2 p-3.5">
              {plan.acceptanceCriteria.map((c) => (
                <li key={c.text} className="grid grid-cols-[18px_1fr] gap-2">
                  {CRITERION_MARK[c.status]}
                  <span>{c.text}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
      <ControlPlan plan={plan} />
      <Routing plan={plan} />
    </>
  );
}
