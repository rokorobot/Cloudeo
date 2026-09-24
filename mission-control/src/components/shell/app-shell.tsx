"use client";

import { useSyncExternalStore, type ReactNode } from "react";

import { CommandPalette } from "@/components/shell/command-palette";
import { Inspector } from "@/components/shell/inspector";
import { SideNav } from "@/components/shell/side-nav";
import { StatusBar } from "@/components/shell/status-bar";
import { TopBar } from "@/components/shell/top-bar";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { useInspector } from "@/state/mission-control";

const WIDE = "(min-width: 1024px)";

function useIsWide() {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(WIDE);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => window.matchMedia(WIDE).matches,
    () => true,
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const inspector = useInspector();
  const wide = useIsWide();
  const showInspector = inspector.open && wide;

  return (
    <div className="grid h-full grid-cols-[56px_1fr] grid-rows-[48px_1fr_32px] [grid-template-areas:'top_top'_'nav_main'_'status_status'] lg:grid-cols-[212px_1fr]">
      <div className="[grid-area:top]">
        <TopBar />
      </div>
      <div className="min-h-0 [grid-area:nav]">
        <SideNav />
      </div>
      <div className="min-h-0 min-w-0 [grid-area:main]">
        <ResizablePanelGroup orientation="horizontal" id="cloudeo-workspace">
          <ResizablePanel id="main" minSize={420}>
            <main className="h-full overflow-y-auto">{children}</main>
          </ResizablePanel>
          {showInspector && (
            <>
              <ResizableHandle />
              <ResizablePanel id="inspector" defaultSize={284} minSize={240} maxSize={420}>
                <Inspector />
              </ResizablePanel>
            </>
          )}
        </ResizablePanelGroup>
      </div>
      <div className="[grid-area:status]">
        <StatusBar />
      </div>
      <CommandPalette />
    </div>
  );
}
