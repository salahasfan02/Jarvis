/* Jarvis desktop shell.
 *
 * Wraps the web UI in a native macOS window with vibrancy, a menu-bar (tray)
 * icon, a global shortcut (Cmd+Shift+J) that toggles a floating assistant
 * window, and native notifications. It also launches the Python backend if
 * it isn't already running.
 *
 * Dev:  npm start          (loads http://localhost:5173 from `npm run dev`)
 * Prod: build the frontend first (npm run build in ../frontend), then package.
 */
const { app, BrowserWindow, Tray, Menu, globalShortcut, ipcMain, nativeImage, shell } = require("electron");

// The wake word needs audio running without a click first, and the listener
// must keep working while the window is hidden or behind other apps.
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { startScreenActivityFrame } = require("./overlay.cjs");

const DEV_URL = "http://localhost:5173";
// Packaged builds carry the UI in renderer/; dev loads Vite or the repo build.
const PROD_INDEX = app.isPackaged
  ? path.join(__dirname, "renderer", "index.html")
  : path.join(__dirname, "..", "frontend", "dist", "index.html");

// The Python backend lives in the repo, not inside the .app. Resolution order:
// env var > ~/.jarvis/backend_path (written at package time) > repo-relative.
function backendDir() {
  if (process.env.JARVIS_BACKEND_DIR) return process.env.JARVIS_BACKEND_DIR;
  const marker = path.join(os.homedir(), ".jarvis", "backend_path");
  try {
    const p = fs.readFileSync(marker, "utf8").trim();
    if (p && fs.existsSync(p)) return p;
  } catch { /* marker not written yet */ }
  return path.join(__dirname, "..", "backend");
}
const BACKEND_DIR = backendDir();

let mainWindow = null;
let floatWindow = null;
let quickWindow = null;
let tray = null;
let backendProc = null;

// The built UI is served by the backend (same origin as the API) rather than
// from file://, whose "null" origin the backend refuses: any website can
// borrow that origin with a sandboxed iframe.
const APP_URL = "http://127.0.0.1:8765/app/";

function quickUrl() {
  if (isDev && !fs.existsSync(PROD_INDEX)) return `${DEV_URL}/quick.html`;
  return `${APP_URL}quick.html`;
}

const isDev = !app.isPackaged;

function checkBackend(cb) {
  http.get("http://127.0.0.1:8765/api/status", (res) => cb(res.statusCode === 200))
    .on("error", () => cb(false));
}

function startBackend() {
  checkBackend((up) => {
    if (up) return;
    const python = path.join(BACKEND_DIR, ".venv", "bin", "python");
    // Packaged: serve the UI bundled in the .app; dev: the repo's frontend/dist.
    const env = { ...process.env };
    if (app.isPackaged) env.JARVIS_UI_DIR = path.dirname(PROD_INDEX);
    backendProc = spawn(python, ["run.py"], { cwd: BACKEND_DIR, stdio: "ignore", env });
  });
}

/** Load the built UI from the backend once it answers (it may still be starting). */
function loadFromBackend(win, url = APP_URL, tries = 0) {
  checkBackend((up) => {
    if (win.isDestroyed()) return;
    if (up) return win.loadURL(url);
    if (tries === 0) {
      win.loadURL("data:text/html," + encodeURIComponent(
        "<body style='background:#000;color:#3f6;font:14px monospace;display:grid;" +
        "place-items:center;height:100vh;margin:0'>Starting Jarvis…</body>"));
    }
    if (tries < 60) setTimeout(() => loadFromBackend(win, url, tries + 1), 500);
  });
}

function loadUI(win) {
  if (isDev && !fs.existsSync(PROD_INDEX)) win.loadURL(DEV_URL);
  else if (isDev) {
    // Dev with a built frontend available: prefer live Vite if it responds.
    http.get(DEV_URL, () => win.loadURL(DEV_URL))
      .on("error", () => loadFromBackend(win));
  } else loadFromBackend(win);
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 800,
    minHeight: 560,
    titleBarStyle: "hiddenInset",
    vibrancy: "under-window",
    visualEffectState: "active",
    backgroundColor: "#00000000",
    webPreferences: { contextIsolation: true, backgroundThrottling: false },
  });
  loadUI(mainWindow);
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.on("closed", () => (mainWindow = null));
}

function toggleFloatWindow() {
  if (floatWindow && !floatWindow.isDestroyed()) {
    floatWindow.isVisible() ? floatWindow.hide() : floatWindow.show();
    return;
  }
  const { screen } = require("electron");
  const display = screen.getPrimaryDisplay().workAreaSize;
  floatWindow = new BrowserWindow({
    width: 460,
    height: 640,
    x: display.width - 480,
    y: 40,
    frame: false,
    alwaysOnTop: true,
    vibrancy: "hud",
    visualEffectState: "active",
    backgroundColor: "#00000000",
    resizable: true,
    skipTaskbar: true,
    webPreferences: { contextIsolation: true, backgroundThrottling: false },
  });
  loadUI(floatWindow);
}

function hideQuick() {
  if (quickWindow && !quickWindow.isDestroyed() && quickWindow.isVisible()) {
    quickWindow.hide();
  }
}

function showQuick() {
  // A 'panel'-type window is an NSNonactivatingPanel on macOS: show() makes it
  // the key window (so it accepts typing) WITHOUT activating the Jarvis app,
  // so it floats over whatever app you're in and that app stays frontmost.
  // NB: level "floating" (not "screen-saver") — screen-saver level sits above
  // the menu bar and can trap interaction, freezing the main window.
  quickWindow.setAlwaysOnTop(true, "floating");
  quickWindow.show();
  quickWindow.webContents.executeJavaScript("window.jarvisFocus && window.jarvisFocus()")
    .catch(() => {});
}

function toggleQuickWindow() {
  if (quickWindow && !quickWindow.isDestroyed()) {
    if (quickWindow.isVisible()) { hideQuick(); return; }
    showQuick();
    return;
  }
  const { screen } = require("electron");
  const { width } = screen.getPrimaryDisplay().workAreaSize;
  quickWindow = new BrowserWindow({
    width: 620,
    height: 200,
    x: Math.round((width - 620) / 2),
    y: 160,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    hasShadow: false,
    type: "panel",              // non-activating panel — the key to not stealing focus
    vibrancy: "hud",
    webPreferences: { contextIsolation: true, preload: path.join(__dirname, "quick-preload.cjs") },
  });
  // visible across spaces, but NOT forced above fullscreen (that combination
  // with a panel is what wedged the window manager).
  quickWindow.setVisibleOnAllWorkspaces(true);
  quickWindow.loadURL(quickUrl());
  quickWindow.once("ready-to-show", showQuick);
  quickWindow.on("blur", hideQuick);
  quickWindow.on("closed", () => { quickWindow = null; });
}

function createTray() {
  const icon = nativeImage.createFromDataURL(
    // 16x16 template circle
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAoUlEQVQ4je2SsQ3CMBBFn5NIFBQMwAY0DMAGMAIjMAIbwAZkAxggFRUFEgW5FDaKHTvBSkfBl67x+X/dP58BwzAK1lqcc78ZSCkBWGvRWv9uUJYlIQTGGKy1eXVKKUopKKUwxswzSCkRQmCM+bpBRJimKZ9BCIExhpQSAGvtvIH3HhFBRJhSAmCM+d5ARJhSAsA5N88ghADnHM45Sqm/3+AF6BpTC/HPBDkAAAAASUVORK5CYII="
  );
  icon.setTemplateImage(true);
  tray = new Tray(icon);
  tray.setToolTip("Jarvis");
  rebuildTrayMenu();
}

function rebuildTrayMenu() {
  const openAtLogin = app.getLoginItemSettings().openAtLogin;
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Open Jarvis", click: () => (mainWindow ? mainWindow.show() : createMainWindow()) },
    { label: "Quick command  ⌥Space", click: toggleQuickWindow },
    { label: "Floating assistant  ⌘⇧J", click: toggleFloatWindow },
    { type: "separator" },
    {
      label: "Open at Login",
      type: "checkbox",
      checked: openAtLogin,
      click: () => {
        app.setLoginItemSettings({ openAtLogin: !openAtLogin });
        rebuildTrayMenu();
      },
    },
    { type: "separator" },
    { label: "Quit", click: () => app.quit() },
  ]));
}

ipcMain.on("quick-hide", () => hideQuick());

// Capture the screen for the 👁 feature with the Jarvis panel hidden, so the
// OCR reads the app the user is actually looking at (not our own bar).
ipcMain.handle("quick-capture-screen", async () => {
  const wasVisible = quickWindow && quickWindow.isVisible();
  if (wasVisible) quickWindow.hide();
  await new Promise((r) => setTimeout(r, 180));  // let the compositor update
  let text = "";
  try {
    const res = await fetch("http://127.0.0.1:8765/api/screen-ocr", { method: "POST" });
    const data = await res.json();
    text = data.text || "";
  } catch { /* backend unreachable */ }
  if (wasVisible) { quickWindow.show(); }
  return text;
});

app.whenReady().then(() => {
  startBackend();
  createMainWindow();
  createTray();
  globalShortcut.register("CommandOrControl+Shift+J", toggleFloatWindow);
  globalShortcut.register("Alt+Space", toggleQuickWindow);
  startScreenActivityFrame();   // frame around the screen while Jarvis reads/controls it
});

app.on("window-all-closed", () => {
  /* keep running in the tray, JARVIS-style */
});

app.on("activate", () => {
  if (!mainWindow) createMainWindow();
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
  if (backendProc) backendProc.kill();
});
