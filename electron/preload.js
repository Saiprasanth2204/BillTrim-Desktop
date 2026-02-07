const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electronAPI', {
  getBackendUrl: () => ipcRenderer.invoke('get-backend-url'),
  checkBackendHealth: () => ipcRenderer.invoke('check-backend-health'),
  restartBackend: () => ipcRenderer.invoke('restart-backend'),
  checkLicense: () => ipcRenderer.invoke('check-license'),
  storeLicense: (licenseKey) => ipcRenderer.invoke('store-license', licenseKey),
  clearLicense: () => ipcRenderer.invoke('clear-license'),
});

// Expose desktop mode variables BEFORE React loads
// This runs in the isolated context before any page scripts execute
// These will be available as window.__DESKTOP_MODE__ and window.__API_URL__
contextBridge.exposeInMainWorld('__DESKTOP_MODE__', true);
contextBridge.exposeInMainWorld('__API_URL__', 'http://localhost:8765/api/v1');
