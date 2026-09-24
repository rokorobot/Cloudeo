"use client";

import { useState, type ReactNode } from "react";

import { HttpWorkOrderQuerySource } from "@/data/control-source";
import { FixtureWorkOrderProvider } from "@/data/fixture-provider";
import { V2WorkOrderProvider } from "@/data/v2-provider";
import type { DataSource } from "@/lib/types";

/** Mounts the demo or the control-backed provider. The screens are identical. */
export function WorkOrderDataProvider({ source, children }: { source: DataSource; children: ReactNode }) {
  const [http] = useState(() => new HttpWorkOrderQuerySource());
  if (source === "control") return <V2WorkOrderProvider source={http}>{children}</V2WorkOrderProvider>;
  return <FixtureWorkOrderProvider>{children}</FixtureWorkOrderProvider>;
}
