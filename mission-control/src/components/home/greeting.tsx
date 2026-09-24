"use client";

import { useSyncExternalStore } from "react";

function greetingFor(hour: number) {
  if (hour < 5) return "Working late.";
  if (hour < 12) return "Good morning.";
  if (hour < 18) return "Good afternoon.";
  return "Good evening.";
}

const noop = () => () => {};

/** Uses the viewer's local clock; the server renders a neutral greeting. */
export function Greeting() {
  const text = useSyncExternalStore(
    noop,
    () => greetingFor(new Date().getHours()),
    () => "Mission control.",
  );
  return <h1 className="mb-3.5 text-[30px] font-medium tracking-[-0.02em]">{text}</h1>;
}
