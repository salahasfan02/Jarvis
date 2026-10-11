import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/global.css";

// The desktop app hides the macOS title bar, so the window needs its own
// strip to drag by (and room for the traffic-light buttons).
if (navigator.userAgent.includes("Electron")) {
  document.documentElement.classList.add("electron");
  const strip = document.createElement("div");
  strip.className = "window-drag";
  document.body.prepend(strip);
  // CSS drag regions break once the window has navigated, so the desktop
  // app moves the window itself while the strip is held.
  const win = (window as any).jarvisWindow;
  if (win) {
    strip.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      strip.setPointerCapture(e.pointerId);
      win.dragStart();
    });
    strip.addEventListener("dblclick", () => win.toggleZoom());   // like a title bar
    const end = () => win.dragEnd();
    for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) strip.addEventListener(ev, end);
    window.addEventListener("blur", end);
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
