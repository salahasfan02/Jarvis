/* Main window bridge: lets the page's title strip move the window.
 * Electron's CSS drag regions stop working after the window navigates
 * ("Starting Jarvis…" -> the app), so dragging is done here instead. */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jarvisWindow", {
  dragStart: () => ipcRenderer.send("window-drag", "start"),
  dragEnd: () => ipcRenderer.send("window-drag", "end"),
  toggleZoom: () => ipcRenderer.send("window-drag", "zoom"),
});
