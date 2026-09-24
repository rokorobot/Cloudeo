"use client";

import { useId, useState } from "react";
import { Clock, Lock, Plus, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import { Dot, Panel, PROVIDER_DOT, PROVIDER_TEXT, SectionLabel } from "@/components/common/status";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { NOT_CONNECTED } from "@/components/work-order/run-controls";
import type { LiveWorkOrder } from "@/data/sources";
import { formatTimestamp, shortSha } from "@/lib/format";
import type { AttentionView } from "@/lib/types";
import { cn } from "@/lib/utils";

const MIN_REASON = 20;

/** The demo attention fixture carries requirement, provider health and override details. */
type DemoAttentionView = AttentionView &
  Required<Pick<AttentionView, "requirement" | "providers" | "override" | "pausedAtCheckpoint" | "since">>;

function isDemoAttention(a: AttentionView): a is DemoAttentionView {
  return !!(a.requirement && a.providers && a.override && a.pausedAtCheckpoint && a.since);
}

function RecoveryAction({
  icon: Icon,
  title,
  detail,
  tag,
  onClick,
}: {
  icon: typeof Clock;
  title: string;
  detail: string;
  tag?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="grid grid-cols-[18px_1fr_auto] items-start gap-x-3 gap-y-0.5 rounded-lg border border-line bg-panel px-3.5 py-3 text-left transition-colors hover:border-input hover:bg-hover"
    >
      <Icon className="mt-0.5 size-4 text-subtle" strokeWidth={1.6} />
      <span>{title}</span>
      <span className="font-mono text-[11px] text-muted-foreground">{tag}</span>
      <span className="col-start-2 col-end-4 text-[12.5px] text-muted-foreground">{detail}</span>
    </button>
  );
}

function OwnerOverrideDialog({ wo, attention }: { wo: LiveWorkOrder; attention: DemoAttentionView }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const reasonId = useId();
  const ackId = useId();
  const valid = reason.trim().length >= MIN_REASON && ack;
  const o = attention.override;

  const reset = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setReason("");
      setAck(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={reset}>
      <DialogTrigger asChild>
        <button
          type="button"
          className="grid grid-cols-[18px_1fr_auto] items-start gap-x-3 gap-y-0.5 rounded-lg border border-dashed border-warn/45 px-3.5 py-3 text-left transition-colors hover:border-warn/70 hover:bg-warn/[0.05]"
        >
          <Lock className="mt-0.5 size-4 text-warn" strokeWidth={1.6} />
          <span>Owner policy override…</span>
          <span className="font-mono text-[11px] text-warn">{o.requiredRole.toUpperCase()}</span>
          <span className="col-start-2 col-end-4 text-[12.5px] text-muted-foreground">
            Amends this WorkOrder&apos;s envelope so final verification may proceed without independence. Needs explicit owner
            approval and becomes part of the WorkOrder evidence.
          </span>
        </button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Lock className="size-4 text-warn" /> Owner policy override for {wo.id}
          </DialogTitle>
          <DialogDescription>
            This is an exception, not a recovery path. It weakens a verification guarantee for this WorkOrder only, and the decision
            is recorded permanently.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="rounded-lg border border-line bg-ground p-3.5">
            <SectionLabel>Envelope amendment</SectionLabel>
            <dl className="mt-2.5 grid grid-cols-[92px_1fr] gap-x-3 gap-y-1.5 text-[12.5px]">
              <dt className="text-muted-foreground">Policy</dt>
              <dd className="font-mono text-[12px] break-all">{o.policyPath}</dd>
              <dt className="text-muted-foreground">Change</dt>
              <dd className="font-mono text-[12px]">
                <span className="text-subtle line-through decoration-muted-foreground">{o.from}</span>
                <span className="mx-2 text-muted-foreground">→</span>
                <span className="text-warn">{o.to}</span>
              </dd>
              <dt className="text-muted-foreground">Scope</dt>
              <dd>{wo.id} only. Project policy is unchanged.</dd>
              <dt className="text-muted-foreground">Approver</dt>
              <dd>{o.requiredRole}</dd>
              <dt className="text-muted-foreground">Evidence</dt>
              <dd>Recorded as a policy amendment with your identity, reason and time. Visible on every later view of this WorkOrder.</dd>
            </dl>
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor={reasonId} className="text-[12.5px]">
              Reason for the override
            </label>
            <Textarea
              id={reasonId}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why is proceeding without an independent verifier acceptable for this WorkOrder?"
              rows={3}
            />
            <span className={cn("text-[11.5px]", reason.trim().length >= MIN_REASON ? "text-muted-foreground" : "text-subtle")}>
              At least {MIN_REASON} characters. This text is stored in evidence.
            </span>
          </div>

          <label htmlFor={ackId} className="flex items-start gap-2.5 text-[12.5px]">
            <input
              id={ackId}
              type="checkbox"
              checked={ack}
              onChange={(e) => setAck(e.target.checked)}
              className="mt-0.5 size-4 accent-[var(--cl-warn)]"
            />
            <span>
              I understand final verification for {wo.id} will not be independent of the executor ({attention.requirement.executorProvider}),
              and that this is recorded against my name.
            </span>
          </label>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => reset(false)}>
            Cancel
          </Button>
          <Button
            disabled={!valid}
            className="bg-warn text-[#1d1606] hover:bg-warn/85"
            onClick={() => {
              reset(false);
              toast("Amendment not submitted", {
                description: "This build has no control store. Nothing was changed and WO-1845 stays paused.",
              });
            }}
          >
            Submit amendment for approval
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DemoAttention({ wo, attention }: { wo: LiveWorkOrder; attention: DemoAttentionView }) {
  const req = attention.requirement;
  return (
    <div className="grid gap-3.5 xl:grid-cols-[minmax(0,640px)_1fr]">
      <Panel role="alert" className="border-warn/40 bg-[linear-gradient(color-mix(in_oklab,var(--cl-warn)_7%,transparent),color-mix(in_oklab,var(--cl-warn)_7%,transparent)),var(--cl-panel)]">
        <header className="flex items-center gap-2.5 border-b border-warn/35 px-4 py-3 text-[11px] font-medium tracking-[0.1em] text-warn">
          <TriangleAlert className="size-4" /> ATTENTION REQUIRED
        </header>

        <div className="flex flex-col gap-3.5 p-4">
          <div className="flex flex-col gap-1">
            <span className="font-mono text-[15px] font-medium tracking-[0.02em]">{attention.code}</span>
            <p className="text-subtle">{attention.headline}</p>
          </div>

          <div className="rounded-lg border border-line bg-ground p-3.5">
            <SectionLabel>Unmet requirement</SectionLabel>
            <dl className="mt-2 grid grid-cols-[120px_1fr] gap-x-3 gap-y-1.5 text-[12.5px]">
              <dt className="text-muted-foreground">Role</dt>
              <dd className="font-mono text-[12px]">{req.role}</dd>
              <dt className="text-muted-foreground">Rule</dt>
              <dd className="font-mono text-[12px]">{req.rule}</dd>
              <dt className="text-muted-foreground">Executor</dt>
              <dd>{req.executorProvider}</dd>
            </dl>
            <ul className="mt-3 flex flex-col gap-1.5 border-t border-line-soft pt-3">
              {attention.providers.map((p) => (
                <li key={p.provider} className="grid grid-cols-[14px_90px_1fr] items-center gap-2 text-[12.5px]">
                  <Dot kind={PROVIDER_DOT[p.status]} />
                  <span>{p.provider}</span>
                  <span className="text-muted-foreground">
                    <span className={PROVIDER_TEXT[p.status]}>{p.status}</span> · {p.detail}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex items-start gap-2.5 rounded-lg border border-line bg-ground px-3 py-2.5 text-[12.5px]">
            <Dot kind="warn" className="mt-1.5" />
            <span>
              Paused at <span className="font-mono text-[12px]">{attention.pausedAtCheckpoint}</span> since {attention.since}.{" "}
              <b className="font-medium">No policy was weakened.</b>{" "}
              <span className="text-subtle">The independence rule is unchanged and nothing was verified by the executor&apos;s own provider.</span>
            </span>
          </div>
        </div>
      </Panel>

      <div className="flex flex-col gap-2.5">
        <SectionLabel>Recovery</SectionLabel>
        <RecoveryAction
          icon={Clock}
          title="Wait for an eligible independent provider"
          tag="RECOMMENDED"
          detail="Cloudeo resumes automatically when OpenAI passes health checks. No action needed."
          onClick={() => toast(`${wo.id} will resume on its own once an independent provider is healthy.`)}
        />
        <RecoveryAction
          icon={Plus}
          title="Add or configure an eligible provider"
          tag="SETTINGS"
          detail="Enable another provider for the final_verifier role, such as Google or a self-hosted verifier."
          onClick={() => toast("Provider configuration is not part of this milestone.")}
        />

        <div className="mt-3 flex items-center gap-2.5">
          <span className="label-caps text-warn">Exceptional</span>
          <span className="h-px flex-1 bg-warn/25" />
        </div>
        <OwnerOverrideDialog wo={wo} attention={attention} />
      </div>
    </div>
  );
}

const REASON_STATUS_CLASS = { open: "text-warn", resolved: "text-ok", waived: "text-subtle" } as const;

/** Control mode: exactly what the open AttentionRequest records, and no actions. */
function ControlAttention({ attention }: { attention: AttentionView }) {
  const reasons = attention.reasons ?? [];
  const waived = reasons.filter((r) => r.status === "waived");
  return (
    <div className="grid gap-3.5 xl:grid-cols-[minmax(0,640px)_1fr]">
      <Panel role="alert" className="border-warn/40 bg-[linear-gradient(color-mix(in_oklab,var(--cl-warn)_7%,transparent),color-mix(in_oklab,var(--cl-warn)_7%,transparent)),var(--cl-panel)]">
        <header className="flex items-center gap-2.5 border-b border-warn/35 px-4 py-3 text-[11px] font-medium tracking-[0.1em] text-warn">
          <TriangleAlert className="size-4" /> ATTENTION REQUIRED
        </header>
        <div className="flex flex-col gap-3.5 p-4">
          <div className="flex flex-col gap-1">
            <span className="font-mono text-[15px] font-medium tracking-[0.02em]">{attention.code}</span>
            <p className="text-subtle">{attention.headline}</p>
          </div>
          <ul className="flex flex-col gap-2.5 rounded-lg border border-line bg-ground p-3.5">
            {reasons.map((r) => (
              <li key={r.code} className="flex flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2.5 text-[12.5px]">
                  <span className="font-mono text-[12px]">{r.code}</span>
                  <span className="text-muted-foreground">{r.severity}</span>
                  <span className={REASON_STATUS_CLASS[r.status]}>{r.status}</span>
                  <span className="flex-1" />
                  <span className="font-mono text-[11px] text-muted-foreground">{r.evidenceCount} evidence refs</span>
                </div>
                <span className="text-[12.5px] text-subtle">{r.summary}</span>
                {r.suggestions.map((s) => (
                  <span key={s} className="text-[12px] text-muted-foreground">Suggested: {s}</span>
                ))}
              </li>
            ))}
          </ul>
          <div className="flex items-start gap-2.5 rounded-lg border border-line bg-ground px-3 py-2.5 text-[12.5px]">
            <Dot kind="warn" className="mt-1.5" />
            <span>
              Raised from <span className="font-mono text-[12px]">{attention.raisedFrom}</span>
              {attention.pausedAtCheckpoint && (
                <>
                  {" "}with accepted checkpoint <span className="font-mono text-[12px]">{shortSha(attention.pausedAtCheckpoint)}</span>
                </>
              )}
              . Nothing proceeds until a decision is recorded.{" "}
              <b className="font-medium">{waived.length ? `${waived.length} reason(s) waived by a recorded decision.` : "No reason has been waived."}</b>
            </span>
          </div>
          {!!attention.decisions?.length && (
            <div className="flex flex-col gap-1.5">
              <SectionLabel>Decisions recorded</SectionLabel>
              {attention.decisions.map((d) => (
                <span key={`${d.action}-${d.at}`} className="text-[12.5px] text-subtle">
                  <span className="font-mono text-[12px] text-foreground">{d.action}</span> by {d.actor} · {formatTimestamp(d.at)}
                  {d.message ? ` · ${d.message}` : ""}
                </span>
              ))}
            </div>
          )}
        </div>
      </Panel>

      <div className="flex flex-col gap-2.5">
        <SectionLabel>Decisions the V2 contract offers</SectionLabel>
        <div className="flex flex-wrap gap-2">
          {(attention.availableDecisions ?? []).map((a) => (
            <Button key={a} variant="outline" size="sm" disabled title={NOT_CONNECTED} className="font-mono">
              {a}
            </Button>
          ))}
        </div>
        <p className="text-[12.5px] text-muted-foreground">{NOT_CONNECTED}. Mission Control is reading the control store; it cannot record decisions.</p>
      </div>
    </div>
  );
}

export function AttentionPanel({ wo, attention }: { wo: LiveWorkOrder; attention: AttentionView }) {
  if (wo.source === "fixture" && isDemoAttention(attention)) return <DemoAttention wo={wo} attention={attention} />;
  return <ControlAttention attention={attention} />;
}
