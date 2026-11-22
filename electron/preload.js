const { contextBridge, ipcRenderer, webUtils } = require('electron');
// Tiny, explicit bridge: pick a file, resolve a dropped file's path, and manage per-provider API keys. Nothing else.
// Keys are stored by the main process (OS-encrypted); the page can store/remove them and reveal one on demand (Show button).
contextBridge.exposeInMainWorld('sv', {
  isElectron: true,
  pickFile: () => ipcRenderer.invoke('pick-file'),
  pickFolder: () => ipcRenderer.invoke('pick-folder'),
  pickGguf: () => ipcRenderer.invoke('pick-gguf'),
  pathForFile: (f) => webUtils.getPathForFile(f),
  keyStatus: () => ipcRenderer.invoke('key-status'),
  setKey: (name, value) => ipcRenderer.invoke('set-key', name, value),
  removeKey: (name) => ipcRenderer.invoke('remove-key', name),
  revealKey: (name) => ipcRenderer.invoke('reveal-key', name),
});
