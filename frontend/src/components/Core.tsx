import { useEffect, useRef } from "react";
import { voiceBus } from "../lib/voice";

export type CoreMode = "idle" | "thinking" | "speaking" | "listening";
export type CoreDesign = "orb" | "reactor" | "halo" | "nebula";

export const CORE_DESIGNS: { id: CoreDesign; name: string }[] = [
  { id: "orb", name: "Orb (particles)" },
  { id: "reactor", name: "Arc reactor" },
  { id: "halo", name: "Halo (minimal)" },
  { id: "nebula", name: "Nebula swarm" },
];

/** The JARVIS core visualization. Four switchable designs share the same
 *  state machine: idle breathes, thinking spins fast, speaking reacts to the
 *  live voice amplitude from voiceBus. */
export function Core({ mode, design = "orb", size = 420, onClick }: {
  mode: CoreMode;
  design?: CoreDesign;
  size?: number;
  onClick?: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const modeRef = useRef<CoreMode>(mode);
  const designRef = useRef<CoreDesign>(design);
  const ampRef = useRef(0);
  const speakingRef = useRef(false);
  modeRef.current = mode;
  designRef.current = design;

  useEffect(() => {
    const onAmp = (e: Event) => (ampRef.current = (e as CustomEvent).detail);
    const onSpeak = (e: Event) => (speakingRef.current = (e as CustomEvent).detail);
    voiceBus.addEventListener("amplitude", onAmp);
    voiceBus.addEventListener("speaking", onSpeak);
    return () => {
      voiceBus.removeEventListener("amplitude", onAmp);
      voiceBus.removeEventListener("speaking", onSpeak);
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    const ctx = canvas.getContext("2d")!;
    // The designs are drawn on a 420px stage and scaled to fit, so a smaller
    // core (next to a reply, in a small window) is the same picture, smaller.
    const S = 420;
    ctx.scale(dpr * (size / S), dpr * (size / S));
    const cx = S / 2;
    const cy = S / 2;

    const particles = Array.from({ length: 90 }, (_, i) => ({
      angle: (Math.PI * 2 * i) / 90 + Math.random(),
      radius: 70 + Math.random() * 110,
      speed: 0.0015 + Math.random() * 0.004,
      size: 0.8 + Math.random() * 1.8,
      wobble: Math.random() * Math.PI * 2,
    }));
    const swarm = Array.from({ length: 260 }, () => ({
      angle: Math.random() * Math.PI * 2,
      radius: 20 + Math.random() * 150,
      speed: (0.001 + Math.random() * 0.006) * (Math.random() > 0.5 ? 1 : -1),
      size: 0.5 + Math.random() * 1.6,
      drift: Math.random() * Math.PI * 2,
    }));

    interface Ring { r: number; alpha: number; }
    let rings: Ring[] = [];
    let raf = 0;
    let t = 0;
    let smoothing = 0;

    const nucleus = (rgb: string, coreR: number, amp: number) => {
      const grad = ctx.createRadialGradient(cx, cy, 4, cx, cy, coreR * 2.2);
      grad.addColorStop(0, "rgba(235, 250, 245, 0.95)");
      grad.addColorStop(0.35, `rgba(${rgb}, ${0.55 + amp * 0.4})`);
      grad.addColorStop(1, `rgba(${rgb}, 0)`);
      ctx.beginPath();
      ctx.arc(cx, cy, coreR * 2.2, 0, Math.PI * 2);
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.beginPath();
      ctx.arc(cx, cy, coreR * 0.62, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(245, 255, 250, ${0.85 + amp * 0.15})`;
      ctx.fill();
    };

    const speakRings = (rgb: string, coreR: number, amp: number, speaking: boolean) => {
      if (speaking && t % 9 === 0 && amp > 0.08) {
        rings.push({ r: coreR + 6, alpha: 0.5 * Math.min(1, amp + 0.3) });
      }
      rings = rings.filter((ring) => ring.alpha > 0.01);
      for (const ring of rings) {
        ring.r += 2.4;
        ring.alpha *= 0.955;
        ctx.beginPath();
        ctx.arc(cx, cy, ring.r, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${rgb}, ${ring.alpha})`;
        ctx.lineWidth = 1.6;
        ctx.stroke();
      }
    };

    const waveform = (rgb: string, amp: number, speaking: boolean) => {
      if (!speaking) return;
      const w = S * 0.5;
      ctx.beginPath();
      for (let x = 0; x <= w; x += 4) {
        const y = cy + S * 0.36 +
          Math.sin(x * 0.09 + t * 0.25) * amp * 16 * Math.sin((x / w) * Math.PI);
        x === 0 ? ctx.moveTo(cx - w / 2 + x, y) : ctx.lineTo(cx - w / 2 + x, y);
      }
      ctx.strokeStyle = `rgba(${rgb}, ${0.35 + amp * 0.5})`;
      ctx.lineWidth = 2;
      ctx.stroke();
    };

    // ---- designs -------------------------------------------------------

    const drawOrb = (rgb: string, amp: number, speedMul: number, speaking: boolean) => {
      const breath = Math.sin(t * 0.02) * 0.5 + 0.5;
      const coreR = 44 + breath * 4 + amp * 26;
      speakRings(rgb, coreR, amp, speaking);
      for (const gr of [92, 132, 168]) {
        ctx.beginPath();
        ctx.arc(cx, cy, gr + amp * 10, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${rgb}, 0.07)`;
        ctx.stroke();
      }
      for (let i = 0; i < 3; i++) {
        const base = t * 0.004 * speedMul + (i * Math.PI * 2) / 3;
        ctx.beginPath();
        ctx.arc(cx, cy, 110 + i * 26, base, base + 0.9);
        ctx.strokeStyle = `rgba(${rgb}, ${0.22 + amp * 0.4})`;
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      for (const p of particles) {
        p.angle += p.speed * speedMul;
        const wob = Math.sin(t * 0.01 + p.wobble) * 6;
        const r = p.radius + wob + amp * 18;
        ctx.beginPath();
        ctx.arc(cx + Math.cos(p.angle) * r, cy + Math.sin(p.angle) * r * 0.92,
                p.size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${rgb}, ${0.25 + amp * 0.5})`;
        ctx.fill();
      }
      nucleus(rgb, coreR, amp);
    };

    const drawReactor = (rgb: string, amp: number, speedMul: number, speaking: boolean) => {
      const coreR = 34 + amp * 18;
      speakRings(rgb, coreR + 60, amp, speaking);
      // segmented rings, alternating rotation
      const ringsSpec = [
        { r: 66, segs: 10, w: 10, dir: 1 },
        { r: 96, segs: 14, w: 7, dir: -1 },
        { r: 126, segs: 20, w: 5, dir: 1 },
      ];
      for (const spec of ringsSpec) {
        const rot = t * 0.003 * speedMul * spec.dir;
        const gap = (Math.PI * 2) / spec.segs;
        for (let i = 0; i < spec.segs; i++) {
          const a0 = rot + i * gap;
          ctx.beginPath();
          ctx.arc(cx, cy, spec.r + amp * 8, a0, a0 + gap * 0.62);
          ctx.strokeStyle = `rgba(${rgb}, ${0.3 + amp * 0.45})`;
          ctx.lineWidth = spec.w;
          ctx.stroke();
        }
      }
      // spokes
      for (let i = 0; i < 8; i++) {
        const a = (i * Math.PI) / 4 + t * 0.001 * speedMul;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(a) * (coreR + 8), cy + Math.sin(a) * (coreR + 8));
        ctx.lineTo(cx + Math.cos(a) * 58, cy + Math.sin(a) * 58);
        ctx.strokeStyle = `rgba(${rgb}, 0.35)`;
        ctx.lineWidth = 2.5;
        ctx.stroke();
      }
      nucleus(rgb, coreR, amp);
    };

    const drawHalo = (rgb: string, amp: number, speedMul: number, speaking: boolean) => {
      const breath = Math.sin(t * 0.015 * speedMul) * 0.5 + 0.5;
      const R = 100 + breath * 6 + amp * 22;
      speakRings(rgb, R, amp, speaking);
      // soft outer glow ring
      for (let i = 0; i < 4; i++) {
        ctx.beginPath();
        ctx.arc(cx, cy, R + i * 2.5, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${rgb}, ${(0.35 + amp * 0.4) / (i + 1)})`;
        ctx.lineWidth = 2.5 - i * 0.4;
        ctx.stroke();
      }
      // orbiting comet
      const a = t * 0.01 * speedMul;
      ctx.beginPath();
      ctx.arc(cx + Math.cos(a) * R, cy + Math.sin(a) * R, 3.4, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${rgb}, 0.9)`;
      ctx.fill();
      nucleus(rgb, 30 + amp * 16, amp);
    };

    const drawNebula = (rgb: string, amp: number, speedMul: number, speaking: boolean) => {
      speakRings(rgb, 60, amp, speaking);
      for (const p of swarm) {
        p.angle += p.speed * speedMul;
        const r = p.radius + Math.sin(t * 0.008 + p.drift) * 14 + amp * 26;
        const x = cx + Math.cos(p.angle) * r;
        const y = cy + Math.sin(p.angle) * r * 0.8;
        ctx.beginPath();
        ctx.arc(x, y, p.size + amp, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${rgb}, ${0.14 + amp * 0.5 + (p.size / 4)})`;
        ctx.fill();
      }
      nucleus(rgb, 26 + amp * 20, amp);
    };

    const draw = () => {
      t += 1;
      const rgb = getComputedStyle(document.documentElement)
        .getPropertyValue("--core-rgb").trim() || "99, 150, 255";
      const m = modeRef.current;
      const speaking = speakingRef.current;
      const target = speaking ? ampRef.current : 0;
      smoothing += (target - smoothing) * 0.25;
      const amp = smoothing;
      const speedMul = m === "thinking" ? 4 : m === "listening" ? 2 : 1;

      ctx.clearRect(0, 0, S, S);
      switch (designRef.current) {
        case "reactor": drawReactor(rgb, amp, speedMul, speaking); break;
        case "halo": drawHalo(rgb, amp, speedMul, speaking); break;
        case "nebula": drawNebula(rgb, amp, speedMul, speaking); break;
        default: drawOrb(rgb, amp, speedMul, speaking);
      }
      waveform(rgb, amp, speaking);
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [size]);

  return (
    <canvas
      ref={canvasRef}
      onClick={onClick}
      title={onClick ? "Click to change the core design" : undefined}
      style={{ width: size, height: size, cursor: onClick ? "pointer" : "default",
               filter: "drop-shadow(0 0 24px var(--accent-soft))" }}
    />
  );
}
