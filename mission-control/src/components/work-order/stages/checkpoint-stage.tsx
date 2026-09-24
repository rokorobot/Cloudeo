import { Panel, PanelFooter, PanelHeader, SectionLabel } from "@/components/common/status";
import { shortSha } from "@/lib/format";
import type { CheckpointView } from "@/lib/types";
import { cn } from "@/lib/utils";

type Status = CheckpointView["items"][number]["status"];

const STYLE: Record<Status, { ring: string; text: string; label: string }> = {
  baseline: { ring: "border-subtle/60 bg-raised text-subtle", text: "text-subtle", label: "BASELINE" },
  accepted: { ring: "border-ok bg-ok/10 text-ok", text: "text-ok", label: "ACCEPTED" },
  // A candidate is never styled as accepted: dashed, cyan, explicit label.
  candidate: { ring: "border-dashed border-brand bg-brand/10 text-brand", text: "text-brand", label: "CANDIDATE · NOT ACCEPTED" },
  rejected: { ring: "border-dashed border-err bg-err/10 text-err", text: "text-err", label: "REJECTED · KEPT AS EVIDENCE" },
};

const LINK: Record<Status, string> = {
  baseline: "bg-subtle/40",
  accepted: "bg-ok/60",
  candidate: "bg-[repeating-linear-gradient(90deg,var(--cl-brand)_0_5px,transparent_5px_9px)]",
  rejected: "bg-[repeating-linear-gradient(90deg,var(--cl-err)_0_5px,transparent_5px_9px)]",
};

export function CheckpointStage({ checkpoints }: { checkpoints: CheckpointView }) {
  const accepted = checkpoints.items.filter((c) => c.status === "accepted" || c.status === "baseline");
  const head = accepted[accepted.length - 1];
  return (
    <Panel>
      <PanelHeader>
        <SectionLabel>Checkpoint chain</SectionLabel>
        <span className="flex-1" />
        {checkpoints.repo && <span className="font-mono text-[11.5px] text-muted-foreground">git · {checkpoints.repo}</span>}
      </PanelHeader>

      {checkpoints.items.length === 0 ? (
        <p className="p-4.5 text-subtle">No baseline or checkpoint is recorded yet.</p>
      ) : (
        <ol aria-label="Checkpoints" className="flex items-start overflow-x-auto px-4.5 pt-6 pb-5">
          {checkpoints.items.map((c, i) => {
            const s = STYLE[c.status];
            const next = checkpoints.items[i + 1];
            return (
              <li key={`${c.id}-${c.status}-${i}`} className="flex flex-1 items-start last:flex-none" data-status={c.status}>
                <div className="flex min-w-[104px] flex-col items-center gap-1.5 text-center">
                  <span className={cn("grid size-8 place-items-center rounded-full border-[1.5px] font-mono text-[11px]", s.ring)}>{c.id}</span>
                  <span className={cn("font-mono text-[11px]", c.sha ? "text-subtle" : "text-muted-foreground")} title={c.sha}>
                    {shortSha(c.sha) ?? "no commit yet"}
                  </span>
                  <span className="max-w-[140px] text-[11.5px] text-subtle">{c.label}</span>
                  <span className={cn("font-mono text-[10.5px] tracking-[0.06em]", s.text)}>{s.label}</span>
                  {c.auditedBy && <span className="text-[11px] text-muted-foreground">audited by {c.auditedBy}</span>}
                </div>
                {next && <span aria-hidden className={cn("mt-4 h-[1.5px] min-w-6 flex-1", LINK[next.status])} />}
              </li>
            );
          })}
        </ol>
      )}

      <PanelFooter>
        <span className="text-[12.5px] text-subtle">
          {head ? (
            <>
              Accepted head is <span className="font-mono text-foreground">{head.id} · {shortSha(head.sha)}</span>.{" "}
            </>
          ) : null}
          The accepted checkpoint never advances before audit; a rejected candidate stays as evidence and work resumes from the accepted head.
        </span>
      </PanelFooter>
    </Panel>
  );
}
