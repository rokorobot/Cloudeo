"use client";

import { useEffect, useRef } from "react";

/**
 * Cloudeo node-cluster mark: seven cooperating nodes in a loose cloud outline.
 * While work is active, a few cyan signals travel along the edges; otherwise
 * the mark is static. Honours prefers-reduced-motion and pauses when hidden.
 */

const W = 52;
const H = 40;
const NODES: [number, number][] = [
  [8, 28], [16, 16], [27, 10], [38, 16], [45, 27], [34, 30], [20, 30],
];
const EDGES: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 0], [1, 6], [2, 5], [3, 5],
];

interface Signal { edge: number; t: number; speed: number }

export function CloudeoMark({ active, className }: { active: boolean; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const activeRef = useRef(active);
  const redrawRef = useRef<() => void>(() => {});

  useEffect(() => {
    activeRef.current = active;
    // Restart the loop when work resumes; draw one static frame when it stops.
    redrawRef.current();
  }, [active]);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.scale(dpr, dpr);

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const signals: Signal[] = [
      { edge: 0, t: 0, speed: 0.012 },
      { edge: 4, t: 0.5, speed: 0.009 },
      { edge: 8, t: 0.2, speed: 0.014 },
    ];
    const style = getComputedStyle(document.documentElement);
    const text = style.getPropertyValue("--cl-text").trim() || "#ece7de";
    const brand = style.getPropertyValue("--cl-brand").trim() || "#5cc8ff";

    let frame = 0;
    const draw = () => {
      ctx.clearRect(0, 0, W, H);
      ctx.globalAlpha = 0.28;
      ctx.strokeStyle = text;
      ctx.lineWidth = 1.2;
      for (const [a, b] of EDGES) {
        ctx.beginPath();
        ctx.moveTo(...NODES[a]);
        ctx.lineTo(...NODES[b]);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      ctx.fillStyle = text;
      for (const [x, y] of NODES) {
        ctx.beginPath();
        ctx.arc(x, y, 2.4, 0, Math.PI * 2);
        ctx.fill();
      }

      if (activeRef.current) {
        ctx.fillStyle = brand;
        for (const s of signals) {
          if (!reduce) {
            s.t += s.speed;
            if (s.t >= 1) {
              const end = EDGES[s.edge][1];
              const next = EDGES.map((_, i) => i).filter((i) => EDGES[i][0] === end);
              s.edge = next.length ? next[Math.floor(Math.random() * next.length)] : (s.edge + 1) % EDGES.length;
              s.t = 0;
            }
          }
          const [a, b] = EDGES[s.edge];
          const x = NODES[a][0] + (NODES[b][0] - NODES[a][0]) * s.t;
          const y = NODES[a][1] + (NODES[b][1] - NODES[a][1]) * s.t;
          ctx.beginPath();
          ctx.arc(x, y, 2.6, 0, Math.PI * 2);
          ctx.fill();
        }
      }
      if (!reduce && !document.hidden && activeRef.current) frame = requestAnimationFrame(draw);
    };

    const onVisibility = () => {
      cancelAnimationFrame(frame);
      if (!document.hidden) draw();
    };
    redrawRef.current = () => {
      cancelAnimationFrame(frame);
      draw();
    };
    draw();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <canvas
      ref={ref}
      role="img"
      aria-label={active ? "Cloudeo: work in progress" : "Cloudeo: idle"}
      className={className}
      style={{ width: W / 2, height: H / 2 }}
    />
  );
}
