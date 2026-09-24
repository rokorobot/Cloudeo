"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot,
  CirclePlay,
  FolderKanban,
  Gauge,
  House,
  ListChecks,
  PanelTop,
  ShieldCheck,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import { ACTIVE, ATTENTION } from "@/fixtures/work-orders";
import { Dot } from "@/components/common/status";
import { cn } from "@/lib/utils";

interface Item {
  href: string;
  label: string;
  icon: LucideIcon;
  count?: number;
  tone?: "warn";
  match?: (path: string) => boolean;
}

const isAttentionWorkOrder = (p: string) =>
  ATTENTION.some((wo) => p.toUpperCase().startsWith(`/WORK-ORDERS/${wo.id}`));

const PRIMARY: Item[] = [
  { href: "/", label: "Home", icon: House, match: (p) => p === "/" },
  { href: "/runs", label: "Runs", icon: CirclePlay, count: ACTIVE.length, match: (p) => p.startsWith("/runs") || (p.startsWith("/work-orders") && !isAttentionWorkOrder(p)) },
  { href: "/attention", label: "Attention", icon: TriangleAlert, count: ATTENTION.length, tone: "warn", match: (p) => p.startsWith("/attention") || isAttentionWorkOrder(p) },
];

const SECONDARY: Item[] = [
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/browsers", label: "Browsers", icon: PanelTop },
  { href: "/evidence", label: "Evidence", icon: ShieldCheck },
  { href: "/profiles", label: "Profiles", icon: ListChecks },
  { href: "/usage", label: "Usage", icon: Gauge },
];

function NavLink({ item, path }: { item: Item; path: string }) {
  const on = item.match ? item.match(path) : path.startsWith(item.href);
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={on ? "page" : undefined}
      title={item.label}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-subtle transition-colors hover:bg-hover hover:text-foreground",
        on && "bg-raised text-foreground",
      )}
    >
      <Icon className="size-[15px] shrink-0 opacity-85" strokeWidth={1.6} />
      <span className="max-lg:sr-only">{item.label}</span>
      {item.count !== undefined && (
        <span className={cn("ml-auto font-mono text-[11px] text-muted-foreground max-lg:hidden", item.tone === "warn" && "text-warn")}>
          {item.count}
        </span>
      )}
    </Link>
  );
}

export function SideNav() {
  const path = usePathname();
  return (
    <nav aria-label="Workspace" className="flex h-full flex-col gap-0.5 overflow-y-auto border-r border-line px-2.5 py-3.5">
      <span className="label-caps px-2.5 pt-1 pb-1.5 max-lg:hidden">Workspace</span>
      {PRIMARY.map((i) => <NavLink key={i.href} item={i} path={path} />)}
      <div className="mx-2 my-2.5 h-px bg-line-soft" />
      {SECONDARY.map((i) => <NavLink key={i.href} item={i} path={path} />)}
      <div className="mx-2 my-2.5 h-px bg-line-soft" />
      <NavLink item={{ href: "/projects", label: "Projects", icon: FolderKanban }} path={path} />
      <div className="flex flex-col gap-0.5 pl-6 max-lg:hidden">
        <Link href="/projects" className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[12.5px] text-subtle hover:bg-hover hover:text-foreground">
          <Dot kind="running" /> HumanoidOnline
        </Link>
        <Link href="/projects" className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[12.5px] text-subtle hover:bg-hover hover:text-foreground">
          <Dot kind="idle" /> Cloudeo core
        </Link>
      </div>
    </nav>
  );
}
