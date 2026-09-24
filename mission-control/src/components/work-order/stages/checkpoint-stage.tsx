import { Panel, PanelFooter, PanelHeader, SectionLabel } from "@/components/common/status";
import type { CheckpointView } from "@/lib/types";
import { cn } from "@/lib/utils";

export function CheckpointStage({ checkpoints }: { checkpoints: CheckpointView }) {
  const accepted = checkpoints.items.filter((c) => c.status === "accepted");
  const head = accepted[accepted.length - 1];
  return (
    <Panel>
      <PanelHeader>
        <SectionLabel>Checkpoint chain</SectionLabel>
        <span className="flex-1" />
        <span className="font-mono text-[11.5px] text-muted-foreground">git · {checkpoints.repo}</span>
      </PanelHeader>

      <ol aria-label="Checkpoints" className="flex items-start overflow-x-auto px-4.5 pt-6 pb-5">
        {checkpoints.items.map((c, i) => {
          const candidate = c.status === "candidate";
          return (
            <li key={c.id} className="flex flex-1 items-start last:flex-none">
              <div className="flex min-w-[104px] flex-col items-center gap-1.5 text-center">
                <span
                  className={cn(
                    "grid size-8 place-items-center rounded-full border-[1.5px] font-mono text-[11px]",
                    candidate ? "border-dashed border-brand bg-brand/10 text-brand" : "border-ok bg-ok/10 text-ok",
                  )}
                >
                  {c.id}
                </span>
                <span className={cn("font-mono text-[11px]", candidate ? "text-muted-foreground" : "text-subtle")}>{c.sha}</span>
                <span className="text-[11.5px] text-subtle">{c.label}</span>
                <span className={cn("font-mono text-[10.5px] tracking-[0.06em]", candidate ? "text-brand" : "text-ok")}>
                  {candidate ? "CANDIDATE · NOT AUDITED" : "ACCEPTED"}
                </span>
                {c.auditedBy && <span className="text-[11px] text-muted-foreground">audited by {c.auditedBy}</span>}
              </div>
              {i < checkpoints.items.length - 1 && (
                <span
                  aria-hidden
                  className={cn(
                    "mt-4 h-[1.5px] min-w-6 flex-1",
                    checkpoints.items[i + 1].status === "candidate"
                      ? "bg-[repeating-linear-gradient(90deg,var(--cl-brand)_0_5px,transparent_5px_9px)]"
                      : "bg-ok/60",
                  )}
                />
              )}
            </li>
          );
        })}
      </ol>

      <PanelFooter>
        <span className="text-[12.5px] text-subtle">
          Accepted head is <span className="font-mono text-foreground">{head?.id} · {head?.sha}</span>. The accepted checkpoint never
          advances before audit; a rejected candidate stays as evidence and work resumes from the accepted head.
        </span>
      </PanelFooter>
    </Panel>
  );
}
