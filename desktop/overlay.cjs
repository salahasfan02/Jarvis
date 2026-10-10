/* Screen-activity frame.
 *
 * While Jarvis reads the screen (screenshot, OCR, screen memory, a watch) or
 * controls it (clicking), a glowing frame is drawn around every display with
 * a small label, so the user always knows. The backend reports the state at
 * /api/screen/activity; this polls it and shows/hides click-through overlay
 * windows that sit above everything, including full-screen apps.
 */
const { BrowserWindow, screen } = require("electron");
const http = require("http");

const POLL_MS = 200;
const COLORS = {
  reading: "0, 255, 102",      // Jarvis green
  watching: "0, 200, 255",     // calm blue: a long-running watch
  controlling: "255, 160, 0",  // amber: it is moving your mouse
};

const PAGE = `<!doctype html><html><head><meta charset="utf-8"><style>
  html, body { margin: 0; height: 100%; overflow: hidden; background: transparent; }
  #frame { position: fixed; inset: 0; border: 3px solid rgba(var(--c), 0.95);
           box-shadow: inset 0 0 22px rgba(var(--c), 0.55), inset 0 0 4px rgba(var(--c), 0.9);
           animation: pulse 1.6s ease-in-out infinite; }
  #label { position: fixed; top: 34px; left: 50%; transform: translateX(-50%);
           padding: 5px 14px; border-radius: 999px; font: 600 12px -apple-system, sans-serif;
           letter-spacing: .02em; color: #fff; background: rgba(var(--c), 0.85);
           box-shadow: 0 0 16px rgba(var(--c), 0.6); white-space: nowrap; }
  @keyframes pulse { 50% { border-color: rgba(var(--c), 0.45);
                           box-shadow: inset 0 0 12px rgba(var(--c), 0.3); } }
</style></head><body><div id="frame"></div><div id="label"></div><script>
  window.setMode = (rgb, text, showLabel) => {
    document.documentElement.style.setProperty("--c", rgb);
    const l = document.getElementById("label");
    l.textContent = text; l.style.display = showLabel ? "block" : "none";
  };
</script></body></html>`;

let overlays = [];   // one per display
let shownMode = null;
let timer = null;

function makeOverlay(display, primary) {
  const { x, y, width, height } = display.bounds;
  const win = new BrowserWindow({
    x, y, width, height,
    frame: false, transparent: true, resizable: false, movable: false,
    focusable: false, skipTaskbar: true, hasShadow: false, show: false,
    enableLargerThanScreen: true, type: "panel",
    webPreferences: { contextIsolation: true, backgroundThrottling: false },
  });
  win.setIgnoreMouseEvents(true);                     // clicks pass straight through
  win.setAlwaysOnTop(true, "screen-saver");
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.setContentProtection(true);                     // keep it out of screenshots where possible
  win.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(PAGE));
  win.primary = primary;
  return win;
}

function show(mode, label) {
  if (!overlays.length || overlays.some((w) => w.isDestroyed())) {
    hide(true);
    const primaryId = screen.getPrimaryDisplay().id;
    overlays = screen.getAllDisplays().map((d) => makeOverlay(d, d.id === primaryId));
  }
  for (const win of overlays) {
    const apply = () => win.webContents
      .executeJavaScript(`setMode(${JSON.stringify(COLORS[mode] || COLORS.reading)}, ` +
                         `${JSON.stringify(label)}, ${win.primary})`)
      .then(() => { if (!win.isDestroyed()) win.showInactive(); })
      .catch(() => {});
    if (win.webContents.isLoading()) win.webContents.once("did-finish-load", apply);
    else apply();
  }
  shownMode = mode;
}

function hide(destroy = false) {
  for (const win of overlays) {
    if (win.isDestroyed()) continue;
    if (destroy) win.destroy(); else win.hide();
  }
  if (destroy) overlays = [];
  shownMode = null;
}

function poll() {
  http.get("http://127.0.0.1:8765/api/screen/activity", (res) => {
    let body = "";
    res.on("data", (c) => (body += c));
    res.on("end", () => {
      try {
        const { mode, label } = JSON.parse(body);
        if (mode && mode !== shownMode) show(mode, label);
        else if (!mode && shownMode) hide();
      } catch { /* backend restarting */ }
    });
  }).on("error", () => { if (shownMode) hide(); });
}

function startScreenActivityFrame() {
  if (timer) return;
  timer = setInterval(poll, POLL_MS);
  // Displays plugged in/out: rebuild the overlays on next show.
  const rebuild = () => { const m = shownMode; hide(true); if (m) shownMode = null; };
  screen.on("display-added", rebuild);
  screen.on("display-removed", rebuild);
  screen.on("display-metrics-changed", rebuild);
}

module.exports = { startScreenActivityFrame };
