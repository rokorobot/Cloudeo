"use client";

import { useState } from "react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useOwnerCommands } from "@/data/context";
import type { LiveWorkOrder } from "@/data/sources";
import type { OwnerCommand, OwnerCommandView } from "@/lib/types";

/**
 * Owner commands on a control-backed WorkOrder (ADR-038). Which commands apply,
 * and why one is disabled, comes from the Cloudeo adapter; this component never
 * decides availability itself. Each command is confirmed, names the record
 * version shown, and is refused (not merged) if the WorkOrder changed meanwhile.
 */

const COPY: Record<OwnerCommand, { label: string; title: string; body: string; danger?: boolean }> = {
  approve_plan: {
    label: "Approve plan",
    title: "Approve this plan?",
    body: "The latest proposed plan version becomes the execution envelope. It is recorded under your name.",
  },
  reject_plan: {
    label: "Reject plan",
    title: "Reject this plan?",
    body: "Rejecting a proposed plan aborts the WorkOrder. This cannot be undone.",
    danger: true,
  },
  resume: {
    label: "Resume",
    title: "Resume this WorkOrder?",
    body: "It returns to the state it was in when attention was raised. No reason is waived.",
  },
  replan: {
    label: "Replan",
    title: "Ask for a new plan?",
    body: "The attention request closes and the WorkOrder returns to plan proposal for a new plan version.",
  },
  defer: {
    label: "Defer",
    title: "Defer this WorkOrder?",
    body: "The attention request closes and the WorkOrder is parked. It can be resumed later.",
  },
  abort: {
    label: "Abort",
    title: "Abort this WorkOrder?",
    body: "The WorkOrder ends. Everything recorded stays in evidence. This cannot be undone.",
    danger: true,
  },
};

export const STALE_MESSAGE = "The WorkOrder changed since it was shown. Nothing was recorded; review the new state and decide again.";

function CommandButton({ wo, view }: { wo: LiveWorkOrder; view: OwnerCommandView }) {
  const { sendCommand, ownerCommandsOff } = useOwnerCommands();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  // The version the owner is deciding on is the one shown when the dialog opened,
  // not whatever the live stream has loaded by the time they confirm.
  const [seen, setSeen] = useState<number | undefined>(undefined);
  const copy = COPY[view.command];
  const blocked = !view.enabled ? view.reason : !sendCommand ? ownerCommandsOff : wo.version === undefined ? "Record version unknown" : null;
  const tone = copy.danger ? "text-err hover:border-err/50 hover:text-err" : "";

  if (blocked) {
    return (
      <Button variant="outline" size="sm" disabled title={blocked ?? undefined} className={tone}>
        {copy.label}
      </Button>
    );
  }

  async function confirm() {
    if (!sendCommand || seen === undefined) return;
    setBusy(true);
    const result = await sendCommand(wo.id, view.command, seen, note.trim());
    setBusy(false);
    setNote("");
    if (result.status === "recorded") toast(`${copy.label}: recorded on ${wo.id} (record v${result.version}).`);
    else if (result.error === "stale_version") toast.error(STALE_MESSAGE);
    else toast.error(`${copy.label} refused: ${result.message}`);
  }

  return (
    <AlertDialog onOpenChange={(open) => setSeen(open ? wo.version : undefined)}>
      <AlertDialogTrigger asChild>
        <Button variant="outline" size="sm" className={tone} disabled={busy}>
          {copy.label}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{copy.title}</AlertDialogTitle>
          <AlertDialogDescription>
            {copy.body} Applies to {wo.id} at record v{seen ?? wo.version} only.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {view.command !== "approve_plan" && view.command !== "reject_plan" && (
          <Textarea
            aria-label="Note for the record (optional)"
            placeholder="Note for the record (optional)"
            maxLength={2000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        )}
        <AlertDialogFooter>
          {seen !== undefined && wo.version !== seen && (
            <span role="status" className="mr-auto self-center text-[12.5px] text-warn">
              Changed to v{wo.version} since you opened this. Confirming will be refused.
            </span>
          )}
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction className={copy.danger ? "bg-err/15 text-err hover:bg-err/25" : undefined} onClick={() => void confirm()}>
            {copy.label}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function OwnerCommandBar({ wo, only }: { wo: LiveWorkOrder; only?: readonly OwnerCommand[] }) {
  const views = (wo.commands ?? []).filter((c) => !only || only.includes(c.command));
  if (!views.length) return null;
  return (
    <div className="flex flex-wrap gap-2" data-testid="owner-commands">
      {views.map((v) => (
        <CommandButton key={v.command} wo={wo} view={v} />
      ))}
    </div>
  );
}
