"use client";

import { Pause, Play, Square } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
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
import { useRunCommands } from "@/data/context";
import type { LiveWorkOrder } from "@/data/sources";

export const NOT_CONNECTED = "Control actions not connected yet";

export function PauseResumeButton({ wo }: { wo: LiveWorkOrder }) {
  const c = useRunCommands(wo.id);
  if (!c) {
    return (
      <Button variant="outline" size="sm" disabled title={NOT_CONNECTED}>
        <Pause /> Pause
      </Button>
    );
  }
  if (wo.mode === "paused") {
    return (
      <Button variant="outline" size="sm" onClick={c.resume}>
        <Play /> Resume
      </Button>
    );
  }
  return (
    <Button variant="outline" size="sm" onClick={c.pause} disabled={wo.mode !== "running"}>
      <Pause /> Pause
    </Button>
  );
}

export function StopButton({ wo }: { wo: LiveWorkOrder }) {
  const c = useRunCommands(wo.id);
  if (!c) {
    return (
      <Button variant="outline" size="sm" disabled title={NOT_CONNECTED}>
        <Square /> Stop
      </Button>
    );
  }
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="outline" size="sm" className="text-err hover:border-err/50 hover:text-err" disabled={wo.mode === "stopped"}>
          <Square /> Stop
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Stop {wo.id}?</AlertDialogTitle>
          <AlertDialogDescription>
            The current candidate for block {wo.execution?.currentBlockId ?? "—"} is discarded. The accepted checkpoint does not change,
            and everything recorded so far stays in evidence. A stopped WorkOrder cannot be resumed; you would amend and restart it.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep running</AlertDialogCancel>
          <AlertDialogAction
            className="bg-err/15 text-err hover:bg-err/25"
            onClick={() => {
              c.stop();
              toast(`${wo.id} stopped. Accepted checkpoint unchanged.`);
            }}
          >
            Stop WorkOrder
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
