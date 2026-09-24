import { Chip, Panel, PanelHeader, SectionLabel, TONE_TEXT } from "@/components/common/status";
import type { FutureStageView, LifecycleStage, StageStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

/** VERIFY and PROMOTE before they are reached: what will happen, and what it waits for. */
export function FutureStage({ stage, view, status }: { stage: LifecycleStage; view: FutureStageView; status: StageStatus }) {
  const reached = status !== "pending";
  return (
    <Panel>
      <PanelHeader>
        <SectionLabel>{stage}</SectionLabel>
        <Chip>{reached ? status.toUpperCase() : "NOT REACHED"}</Chip>
      </PanelHeader>
      <div className="grid gap-6 p-4.5 md:grid-cols-[1.3fr_1fr]">
        <div className="flex flex-col gap-3">
          <p className="max-w-[62ch] text-[13.5px] text-subtle">{view.summary}</p>
          <SectionLabel className="mt-1">{stage === "verify" ? "What will be checked" : "What promotion will do"}</SectionLabel>
          <ol className="flex flex-col gap-2">
            {view.checks.map((c) => (
              <li key={c.text} className="grid grid-cols-[18px_1fr] gap-2">
                <span className="text-muted-foreground">○</span>
                <span>
                  {c.text}
                  {c.detail && <span className="ml-2 font-mono text-[11.5px] text-muted-foreground">{c.detail}</span>}
                </span>
              </li>
            ))}
          </ol>
        </div>
        <div className="flex flex-col gap-2.5">
          <SectionLabel>Waiting on</SectionLabel>
          <ul className="flex flex-col gap-2">
            {view.preconditions.map((p) => (
              <li key={p.text} className="grid grid-cols-[18px_1fr] gap-2">
                <span className={cn(p.met ? "text-ok" : "text-muted-foreground")}>{p.met ? "✓" : "○"}</span>
                <span className={cn(!p.met && "text-subtle")}>{p.text}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      {!!view.facts?.length && (
        <div className="flex flex-col gap-2.5 border-t border-line-soft p-4.5">
          <SectionLabel>Recorded</SectionLabel>
          <dl className="grid max-w-[640px] grid-cols-[170px_1fr] gap-x-3 gap-y-1.5 text-[12.5px]">
            {view.facts.map((f) => (
              <div key={f.label} className="contents">
                <dt className="text-muted-foreground">{f.label}</dt>
                <dd className={cn("font-mono text-[12px] break-all", f.tone && TONE_TEXT[f.tone])}>{f.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </Panel>
  );
}
