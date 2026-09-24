"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  CirclePlay,
  Hand,
  House,
  Layers,
  PanelRight,
  Pause,
  Play,
  TriangleAlert,
} from "lucide-react";

import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command";
import { WORK_ORDERS } from "@/fixtures/work-orders";
import { useOpenWorkOrder, woHref } from "@/lib/routes";
import { LIFECYCLE } from "@/lib/types";
import { useInspector, useLiveWorkOrder, usePalette, useRunControls } from "@/state/mission-control";

const PAGES = [
  { href: "/", label: "Home", icon: House },
  { href: "/runs", label: "Runs", icon: CirclePlay },
  { href: "/attention", label: "Attention", icon: TriangleAlert },
  { href: "/agents", label: "Agents" },
  { href: "/browsers", label: "Browsers" },
  { href: "/evidence", label: "Evidence" },
  { href: "/profiles", label: "Profiles" },
  { href: "/usage", label: "Usage" },
  { href: "/projects", label: "Projects" },
];

export function CommandPalette() {
  const router = useRouter();
  const { open, setOpen } = usePalette();
  const inspector = useInspector();
  const current = useOpenWorkOrder();
  const wo = useLiveWorkOrder(current.id);
  const controls = useRunControls(current.id ?? "");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  const run = (fn: () => void) => {
    setOpen(false);
    fn();
  };

  return (
    <CommandDialog className="sm:max-w-[560px]" open={open} onOpenChange={setOpen} title="Command palette" description="Jump to a WorkOrder or run an action">
      <Command>
        <CommandInput placeholder="Jump to a WorkOrder, stage, or action…" />
        <CommandList>
          <CommandEmpty>Nothing matches. Try a WorkOrder ID like WO-1842.</CommandEmpty>
  
          {wo && (
            <>
              <CommandGroup heading={`${wo.id} · stages`}>
                {LIFECYCLE.map((s) => (
                  <CommandItem key={s} value={`${wo.id} stage ${s}`} onSelect={() => run(() => router.push(woHref(wo.id, s)))}>
                    <Layers />
                    <span className="uppercase tracking-wide">{s}</span>
                    <CommandShortcut>{wo.stages[s]}</CommandShortcut>
                  </CommandItem>
                ))}
              </CommandGroup>
              {wo.execution && (
                <CommandGroup heading={`${wo.id} · actions`}>
                  {wo.mode === "running" && (
                    <CommandItem onSelect={() => run(controls.pause)}><Pause />Pause autonomous execution</CommandItem>
                  )}
                  {wo.mode === "paused" && (
                    <CommandItem onSelect={() => run(controls.resume)}><Play />Resume autonomous execution</CommandItem>
                  )}
                  {wo.mode === "operator" ? (
                    <CommandItem onSelect={() => run(controls.handBack)}><Play />Hand browser back to agent</CommandItem>
                  ) : wo.mode !== "stopped" ? (
                    <CommandItem onSelect={() => run(() => { controls.takeControl(); router.push(woHref(wo.id, "execute")); })}>
                      <Hand />Take control of browser
                    </CommandItem>
                  ) : null}
                </CommandGroup>
              )}
              <CommandSeparator />
            </>
          )}
  
          <CommandGroup heading="WorkOrders">
            {Object.values(WORK_ORDERS).map((w) => (
              <CommandItem key={w.id} value={`${w.id} ${w.title} ${w.reason ?? ""}`} onSelect={() => run(() => router.push(woHref(w.id, w.currentStage)))}>
                {w.attention ? <TriangleAlert className="text-warn" /> : <CirclePlay className="text-brand" />}
                <span className="font-mono text-[12px] text-muted-foreground">{w.id}</span>
                <span className="truncate">{w.title}</span>
                {w.reason && <CommandShortcut className="text-warn">{w.reason}</CommandShortcut>}
              </CommandItem>
            ))}
          </CommandGroup>
  
          <CommandGroup heading="Go to">
            {PAGES.map((p) => {
              const Icon = p.icon;
              return (
                <CommandItem key={p.href} value={`go ${p.label}`} onSelect={() => run(() => router.push(p.href))}>
                  {Icon ? <Icon /> : <span className="size-4" />}
                  {p.label}
                </CommandItem>
              );
            })}
          </CommandGroup>
  
          <CommandGroup heading="View">
            <CommandItem onSelect={() => run(() => inspector.setOpen(!inspector.open))}>
              <PanelRight />
              {inspector.open ? "Hide inspector" : "Show inspector"}
            </CommandItem>
          </CommandGroup>
        </CommandList>
      </Command>
    </CommandDialog>
  );
}
