"use client";

import { ShieldAlert, ShieldCheck, ShieldEllipsis } from "lucide-react";
import { toast } from "sonner";

import { Panel, PanelFooter, SectionLabel, TONE_TEXT } from "@/components/common/status";
import { Button } from "@/components/ui/button";
import type { AuditView } from "@/lib/types";
import { cn } from "@/lib/utils";

const VERDICT = {
  BLOCK_DONE: {
    icon: ShieldCheck,
    band: "border-ok/25 bg-ok/[0.07]",
    text: "text-ok",
    panel: "border-ok/35",
    subtitle: "independently audited, checkpoint proven",
  },
  NOT_YET_PROVEN: {
    icon: ShieldEllipsis,
    band: "border-line-soft bg-raised",
    text: "text-subtle",
    panel: "",
    subtitle: "audited; not proven until its checkpoint is",
  },
  CHECKPOINT_REJECTED: {
    icon: ShieldAlert,
    band: "border-err/30 bg-err/[0.07]",
    text: "text-err",
    panel: "border-err/35",
    subtitle: "checkpoint did not match the audited state",
  },
} as const;

const VERIFICATION_CLASS = { MATCH: "text-ok", MISMATCH: "text-err", PENDING: "text-muted-foreground" } as const;
const VERIFICATION_MARK = { MATCH: "✓", MISMATCH: "✗", PENDING: "" } as const;

export function AuditStage({ audit }: { audit: AuditView }) {
  const v = VERDICT[audit.verdict];
  const Icon = v.icon;
  const record: [string, React.ReactNode, string?][] = [
    ...(audit.executor ? [["Executor", audit.executor] as [string, string]] : []),
    ["Auditor", audit.auditor],
    ...(audit.auditStatus
      ? [["Audit result", `${audit.auditStatus}${audit.authoritative === false ? " · not authoritative" : ""}`, audit.authoritative === false ? "text-warn" : undefined] as [string, string, string?]]
      : []),
    ["Audited HEAD", audit.auditedHead, "font-mono"],
    ["Content SHA", audit.contentSha, "font-mono"],
    ["Checkpoint", audit.checkpoint ?? "none yet", cn("font-mono", !audit.checkpoint && "text-muted-foreground")],
    ["Verification", `${audit.verification} ${VERIFICATION_MARK[audit.verification]}`.trim(), cn("font-mono", VERIFICATION_CLASS[audit.verification])],
  ];

  return (
    <Panel className={v.panel}>
      {/* Verdict band: BLOCK_DONE is a proven state, not a "completed" label. */}
      <header className={cn("flex flex-wrap items-center gap-3 border-b px-4 py-3", v.band)}>
        <Icon className={cn("size-5", v.text)} strokeWidth={1.6} />
        <div className="flex flex-col">
          <span className={cn("font-mono text-[14px] font-medium tracking-[0.04em]", v.text)}>{audit.verdict}</span>
          <span className="text-[12px] text-subtle">
            Block {audit.blockId} · {audit.blockTitle} · {v.subtitle}
          </span>
        </div>
        <span className="flex-1" />
        <span className="font-mono text-[12px] text-muted-foreground">{audit.artifactCount} evidence refs</span>
      </header>

      <div className="grid md:grid-cols-[1.1fr_1fr]">
        <div className="flex flex-col gap-4 p-4">
          <div className="flex flex-col gap-2.5">
            <SectionLabel>Audit record</SectionLabel>
            <dl className="grid grid-cols-[130px_1fr] gap-x-3.5 gap-y-2 text-[12.5px]">
              {record.map(([k, value, cls]) => (
                <div key={k} className="contents">
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className={cn("min-w-0 break-words", cls)}>{value}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="flex flex-col gap-2">
            <SectionLabel>Tests on audited state</SectionLabel>
            {audit.tests.length === 0 ? (
              <span className="text-[12.5px] text-muted-foreground">No test record.</span>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {audit.tests.map((t) => (
                  <li key={t.suite} className="flex items-center gap-3 font-mono text-[12px]">
                    <span className="flex-1">{t.suite}</span>
                    <span className={cn("tnum", t.result === "passed" ? "text-ok" : "text-err")}>
                      {t.counts ? `${t.counts.passed}/${t.counts.total} ` : ""}
                      {t.result}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-2.5 border-line-soft p-4 max-md:border-t md:border-l">
          <SectionLabel>{audit.verdict === "BLOCK_DONE" ? "What was actually proven" : "What is recorded so far"}</SectionLabel>
          <p className="text-[12px] text-muted-foreground">
            From the audit and change records on the audited state, not from the executor&apos;s report.
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
