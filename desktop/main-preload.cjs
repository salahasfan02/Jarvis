/* Main window bridge: lets the page's title strip move the window.
 * Electron's CSS drag regions stop working after the window navigates
 * ("Starting Jarvis…" -> the app), so dragging is done here instead. */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jarvisWindow", {
  dragStart: () => ipcRenderer.send("window-drag", "start"),
  dragEnd: () => ipcRenderer.send("window-drag", "end"),
  toggleZoom: () => ipcRenderer.send("window-drag", "zoom"),
  // "Open Jarvis when I log in": pass true/false to change, nothing to read.
  loginItem: (enabled) => ipcRenderer.invoke("login-item", enabled),
  // Quit and reopen Jarvis (and its backend) so new macOS permissions apply.
  relaunch: () => ipcRenderer.invoke("relaunch"),
});
