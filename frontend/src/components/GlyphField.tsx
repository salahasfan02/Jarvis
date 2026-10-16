import { useEffect, useRef } from "react";

const GLYPHS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/+=";
const CELL = 13;            // px per character
const FPS = 24;

interface Ripple { x: number; y: number; born: number; strength: number }

/** A quiet field of characters with brighter shapes drifting through it. Press
 *  anywhere and a ripple runs out from that spot, lighting and scrambling the
 *  characters it passes; dragging leaves a trail. Left alone it still moves: a
 *  wave of lit characters sweeps across now and then, and gentle ripples rise
 *  on their own. Tinted by the theme. */
export function GlyphField() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current!;
    const ctx = canvas.getContext("2d")!;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let cols = 0, rows = 0, chars: string[] = [], weight: number[] = [], raf = 0, last = 0;
    let ripples: Ripple[] = [];
    let dragging = false, lastDrop = 0, nextAuto = performance.now() + 1200;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    const resize = () => {
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      canvas.style.width = `${window.innerWidth}px`;
      canvas.style.height = `${window.innerHeight}px`;
      cols = Math.ceil(window.innerWidth / CELL);
      rows = Math.ceil(window.innerHeight / CELL);
      chars = Array.from({ length: cols * rows }, () => GLYPHS[(Math.random() * GLYPHS.length) | 0]);
      // Some cells stay empty and the rest vary, so the field reads as texture, not a wall.
      weight = Array.from({ length: cols * rows }, () => (Math.random() < 0.3 ? 0 : 0.35 + Math.random() * 0.65));
      if (still) draw(performance.now());
    };

    // Soft, slowly drifting "ink": a few overlapping waves, 0..1.
    const ink = (cx: number, cy: number, t: number) => {
      const x = cx / cols, y = cy / rows;
      const v = Math.sin(x * 6.0 + t * 0.21) * Math.cos(y * 5.2 - t * 0.17)
        + Math.sin((x + y) * 4.3 - t * 0.13) * 0.8
        + Math.cos(Math.hypot(x - 0.5 - Math.sin(t * 0.05) * 0.2, y - 0.45) * 9 - t * 0.35) * 0.9;
      return Math.max(0, (v - 0.9) / 1.8);
    };

    const draw = (now: number) => {
      const t = now / 1000;
      const styles = getComputedStyle(document.documentElement);
      const rgb = styles.getPropertyValue("--core-rgb").trim() || "0, 255, 102";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
      ctx.font = `${CELL - 3}px ui-monospace, SFMono-Regular, Menlo, monospace`;
      ctx.textBaseline = "top";

      ripples = ripples.filter((r) => now - r.born < 2600);
      const w = window.innerWidth, h = window.innerHeight;
      // The sweep: a soft diagonal band crossing the screen every ~9 s.
      const span = w + h + 600;
      const sweep = ((now / 1000) * 150) % span - 300;
      for (let cy = 0; cy < rows; cy++) {
        for (let cx = 0; cx < cols; cx++) {
          const px = cx * CELL, py = cy * CELL;
          const i = cy * cols + cx;
          let a = weight[i] * (0.045 + ink(cx, cy, still ? 0 : t) * 0.3);
          let lit = 0;
          for (const r of ripples) {
            const age = (now - r.born) / 1000;
            const front = age * 520;                       // px per second
            const d = Math.hypot(px - r.x, py - r.y);
            const band = Math.exp(-((d - front) ** 2) / 3200) * Math.max(0, 1 - age / 2.6) ** 1.5;
            lit += band * r.strength;
          }
          if (!still) {
            const along = px * 0.8 + py * 0.6;               // distance along the sweep's direction
            lit += Math.exp(-((along - sweep) ** 2) / 5000) * 0.45;
          }
          a += lit * 0.7 * (0.4 + weight[i]);
          // Characters flicker now and then, and scramble where a ripple passes.
          if (!still && (Math.random() < 0.004 || (lit > 0.25 && Math.random() < 0.5))) {
            chars[i] = GLYPHS[(Math.random() * GLYPHS.length) | 0];
          }
          if (a < 0.02) continue;
          ctx.fillStyle = `rgba(${rgb}, ${Math.min(a, 0.9).toFixed(3)})`;
          ctx.fillText(chars[i], px, py);
        }
      }
    };

    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      if (now - last < 1000 / FPS) return;
      last = now;
      if (now > nextAuto) {                                 // a ripple of its own
        ripples.push({ x: Math.random() * window.innerWidth, y: Math.random() * window.innerHeight,
                       born: now, strength: 0.5 });
        nextAuto = now + 2500 + Math.random() * 2500;
      }
      draw(now);
    };

    const drop = (e: PointerEvent, strength: number) => {
      ripples.push({ x: e.clientX, y: e.clientY, born: performance.now(), strength });
      if (ripples.length > 12) ripples.shift();
      if (still) draw(performance.now());
    };
    const down = (e: PointerEvent) => { dragging = true; drop(e, 1); };
    const move = (e: PointerEvent) => {
      if (!dragging || performance.now() - lastDrop < 90) return;
      lastDrop = performance.now();
      drop(e, 0.45);
    };
    const up = () => { dragging = false; };

    resize();
    window.addEventListener("resize", resize);
    window.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    if (!still) raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointerdown", down);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, []);

  return <canvas className="matrix-rain" ref={ref} aria-hidden="true" />;
}
