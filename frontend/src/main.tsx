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
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
