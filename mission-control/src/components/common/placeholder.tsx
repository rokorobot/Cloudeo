import Link from "next/link";
import type { LucideIcon } from "lucide-react";

import { PageBody, PageHeader } from "@/components/common/page-header";
import { Panel, SectionLabel } from "@/components/common/status";

/** Polished placeholder for sections outside this milestone. */
export function Placeholder({
  title,
  lead,
  icon: Icon,
  planned,
}: {
  title: string;
  lead: string;
  icon: LucideIcon;
  planned: string[];
}) {
  return (
    <PageBody>
      <PageHeader title={title} lead={lead} />
      <Panel className="flex flex-col gap-4 p-5">
        <div className="flex items-center gap-3">
          <span className="grid size-9 place-items-center rounded-lg border border-line bg-raised text-subtle">
            <Icon className="size-4" strokeWidth={1.6} />
          </span>
          <div className="flex flex-col">
            <span className="font-medium">Not in this milestone</span>
            <span className="text-[12.5px] text-muted-foreground">The UI foundation ships the WorkOrder flow first.</span>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <SectionLabel>Planned</SectionLabel>
          <ul className="flex flex-col gap-1.5 text-subtle">
            {planned.map((p) => (
              <li key={p} className="flex gap-2.5">
                <span className="text-muted-foreground">○</span>
                {p}
              </li>
            ))}
          </ul>
        </div>
        <Link href="/runs" className="self-start text-[12.5px] text-brand hover:underline">
          Go to Runs →
        </Link>
      </Panel>
    </PageBody>
  );
}
