"use client";

import Link from "next/link";
import { PanelRight } from "lucide-react";

import { CloudeoMark } from "@/components/shell/cloudeo-mark";
import { Chip, Dot } from "@/components/common/status";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAnyRunning, useDataSource, useHealth } from "@/data/context";
import { cn } from "@/lib/utils";
import { useInspector, usePalette } from "@/state/ui";

export function TopBar() {
  const running = useAnyRunning();
  const palette = usePalette();
  const inspector = useInspector();
  const source = useDataSource();
  const health = useHealth();
  const degraded = health?.runtimes.filter((r) => r.status !== "healthy").length ?? 0;

  return (
    <header className="flex h-12 items-center gap-4 border-b border-line px-4">
      <Link href="/" className="flex items-center gap-2.5 text-[12px] font-semibold tracking-[0.14em]">
        <CloudeoMark active={running} />
        CLOUDEO
      </Link>
      {source === "fixture" ? (
        <div className="flex items-center gap-2 text-subtle max-md:hidden">
          <span>Project</span>
          <span className="font-medium text-foreground">HumanoidOnline</span>
          <Chip className="ml-1">DEMO DATA</Chip>
        </div>
      ) : (
        <Chip tone="brand">CONTROL STORE · READ-ONLY</Chip>
      )}
      <div className="flex-1" />
      <Tooltip>
        <TooltipTrigger asChild>
          <Link href="/" className="flex items-center gap-2 text-[12px] text-subtle hover:text-foreground">
            <Dot kind={!health ? "idle" : degraded ? "warn" : "ok"} />
            <span className="max-md:hidden">
              {!health ? "Runtime health not reported" : degraded ? `${degraded} runtimes need a look` : "All runtimes healthy"}
            </span>
          </Link>
        </TooltipTrigger>
        <TooltipContent>Runtime health is in the Inspector when no WorkOrder is open</TooltipContent>
      </Tooltip>
      <button
        type="button"
        onClick={() => palette.setOpen(true)}
        className="flex min-w-0 items-center gap-2 rounded-lg border border-line py-1.5 pr-2 pl-3 text-muted-foreground transition-colors hover:border-input hover:text-subtle md:min-w-56"
      >
        <span className="flex-1 text-left max-md:hidden">Jump to, run, or find…</span>
        <kbd className="rounded border border-line px-1.5 font-mono text-[11px] text-subtle">Ctrl K</kbd>
      </button>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={inspector.open ? "Hide inspector" : "Show inspector"}
            aria-pressed={inspector.open}
            onClick={() => inspector.setOpen(!inspector.open)}
            className={cn("rounded-md p-1.5 text-muted-foreground hover:bg-hover hover:text-foreground max-lg:hidden", inspector.open && "text-subtle")}
          >
            <PanelRight className="size-4" strokeWidth={1.6} />
          </button>
        </TooltipTrigger>
        <TooltipContent>{inspector.open ? "Hide inspector" : "Show inspector"}</TooltipContent>
      </Tooltip>
    </header>
  );
}
