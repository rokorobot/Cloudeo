"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

/** Shell UI state (palette, inspector). Independent of where WorkOrders come from. */
interface UiState {
  paletteOpen: boolean;
  setPaletteOpen(open: boolean): void;
  inspectorOpen: boolean;
  setInspectorOpen(open: boolean): void;
}

const Ctx = createContext<UiState | null>(null);

export function UiStateProvider({ children }: { children: ReactNode }) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const value = useMemo(() => ({ paletteOpen, setPaletteOpen, inspectorOpen, setInspectorOpen }), [paletteOpen, inspectorOpen]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

function useUi() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("UiStateProvider missing");
  return ctx;
}

export function usePalette() {
  const ui = useUi();
  return { open: ui.paletteOpen, setOpen: ui.setPaletteOpen };
}

export function useInspector() {
  const ui = useUi();
  return { open: ui.inspectorOpen, setOpen: ui.setInspectorOpen };
}
