"use client";

import { ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { Panel, PanelFooter, SectionLabel, TONE_TEXT } from "@/components/common/status";
import { Button } from "@/components/ui/button";
import type { AuditView } from "@/lib/types";
import { cn } from "@/lib/utils";

export function AuditStage({ audit }: { audit: AuditView }) {
  const done = audit.verdict === "BLOCK_DONE";
  const match = audit.verification === "MATCH";
  const record: [string, React.ReactNode, string?][] = [
    ["Executor", audit.executor],
    ["Auditor", audit.auditor],
    ["Audited HEAD", audit.auditedHead, "font-mono"],
    ["Content SHA", audit.contentSha, "font-mono"],
    ["Checkpoint", audit.checkpoint, "font-mono"],
    ["Verification", `${audit.verification} ${match ? "✓" : "✗"}`, cn("font-mono", match ? "text-ok" : "text-err")],
  ];

  return (
    <Panel className={cn(done && "border-ok/35")}>
      {/* Verdict band: a proven state, not a "completed" label. */}
      <header className={cn("flex flex-wrap items-center gap-3 border-b px-4 py-3", done ? "border-ok/25 bg-ok/[0.07]" : "border-err/30 bg-err/[0.07]")}>
        <ShieldCheck className={cn("size-5", done ? "text-ok" : "text-err")} strokeWidth={1.6} />
        <div className="flex flex-col">
          <span className={cn("font-mono text-[14px] font-medium tracking-[0.04em]", done ? "text-ok" : "text-err")}>{audit.verdict}</span>
          <span className="text-[12px] text-subtle">
            Block {audit.blockId} · {audit.blockTitle} · independently audited, checkpoint accepted
          </span>
        </div>
        <span className="flex-1" />
        <span className="font-mono text-[12px] text-muted-foreground">{audit.artifactCount} artifacts</span>
      </header>

      <div className="grid md:grid-cols-[1.1fr_1fr]">
        <div className="flex flex-col gap-4 p-4">
          <div className="flex flex-col gap-2.5">
            <SectionLabel>Audit record</SectionLabel>
            <dl className="grid grid-cols-[130px_1fr] gap-x-3.5 gap-y-2 text-[12.5px]">
              {record.map(([k, v, cls]) => (
                <div key={k} className="contents">
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className={cn("min-w-0 break-words", cls)}>{v}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="flex flex-col gap-2">
            <SectionLabel>Tests on audited HEAD</SectionLabel>
            <ul className="flex flex-col gap-1.5">
              {audit.tests.map((t) => (
                <li key={t.suite} className="flex items-center gap-3 font-mono text-[12px]">
                  <span className="flex-1">{t.suite}</span>
                  <span className={cn("tnum", t.passed === t.total ? "text-ok" : "text-err")}>
                    {t.passed}/{t.total} passed
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="flex flex-col gap-2.5 border-line-soft p-4 max-md:border-t md:border-l">
          <SectionLabel>What was actually proven</SectionLabel>
          <p className="text-[12px] text-muted-foreground">
            Checked by the auditor against the exported checkpoint, not taken from the executor&apos;s report.
          </p>
          <ul className="flex flex-col gap-2">
            {audit.proven.map((p) => (
              <li key={p.label} className="grid grid-cols-[48px_1fr] items-baseline gap-3">
                <b className={cn("text-right font-mono text-[15px] font-medium tnum", p.tone && TONE_TEXT[p.tone])}>{p.value}</b>
                <span className="text-subtle">{p.label}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <PanelFooter>
        <span className="text-[12.5px] text-muted-foreground">{audit.pendingNote}</span>
        <span className="flex-1" />
        <Button variant="outline" size="sm" onClick={() => toast("The evidence browser is not part of this milestone.")}>
          View evidence
        </Button>
      </PanelFooter>
    </Panel>
  );
}
