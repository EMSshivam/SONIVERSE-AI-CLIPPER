// SONIVERSE AI Clipper - Electron shell. Starts the local Python engine (dashboard server on 127.0.0.1) and shows it in a window.
// API keys are encrypted with the OS (Windows DPAPI via safeStorage) and only passed to the engine as environment variables.
const { app, BrowserWindow, ipcMain, dialog, safeStorage, shell, Menu } = require('electron');
const { spawn } = require('child_process');
const path = require('path'), fs = require('fs'), net = require('net'), http = require('http');

const ROOT = path.resolve(__dirname, '..');
const PY = process.platform === 'win32' ? path.join(ROOT, '.venv', 'Scripts', 'python.exe') : path.join(ROOT, '.venv', 'bin', 'python');
// One independent key slot per provider. Values live only in the OS-encrypted store (safeStorage) and in the engine's memory.
const KEYS = ['GEMINI_PAID_API_KEY', 'GEMINI_FREE_API_KEY', 'GROQ_API_KEY', 'ASSEMBLYAI_API_KEY', 'SUPOCLIP_API_KEY'];
// Providers the user adds in the app store their keys under X_<NAME>_API_KEY (e.g. X_OPENROUTER_API_KEY).
const isKey = (n) => KEYS.includes(n) || /^X_[A-Z0-9]{1,20}_API_KEY$/.test(String(n));
const TOKEN = require('crypto').randomBytes(24).toString('hex');   // per-launch secret: only this process may push keys to the engine
const VIDEO = ['mp4', 'mov', 'mkv', 'webm', 'm4v', 'ts', 'flv', 'avi'];
let win = null, server = null, port = 0, quitting = false;

const keyFile = () => path.join(app.getPath('userData'), 'keys.json');
function readKeyFile() { try { return JSON.parse(fs.readFileSync(keyFile(), 'utf8')); } catch { return {}; } }
// safeStorage: Electron 45 deprecates the synchronous calls; use the async ones when present, sync on older builds.
const hasAsync = typeof safeStorage.encryptStringAsync === 'function';
const enc = async (str) => (hasAsync ? safeStorage.encryptStringAsync(str) : safeStorage.encryptString(str));
const dec = async (b64) => { const b = Buffer.from(b64, 'base64'); return hasAsync ? (await safeStorage.decryptStringAsync(b)).result : safeStorage.decryptString(b); };
async function loadKeys() {
  const j = readKeyFile(), out = {};
  for (const k of Object.keys(j).filter(isKey)) { try { if (j[k]) out[k] = await dec(j[k]); } catch { /* unreadable -> ignored */ } }
  return out;
}
async function encryptionOk() {
  return typeof safeStorage.isAsyncEncryptionAvailable === 'function' ? await safeStorage.isAsyncEncryptionAvailable() : safeStorage.isEncryptionAvailable();
}
async function writeKeys(mutate) {
  if (!(await encryptionOk())) throw new Error('OS encryption is not available - the key was NOT stored');
  const j = readKeyFile(); mutate(j);
  fs.mkdirSync(path.dirname(keyFile()), { recursive: true });
  fs.writeFileSync(keyFile(), JSON.stringify(j), { mode: 0o600 });
}
// Tell the running engine about a key change without restarting it (running jobs are not disturbed).
function pushKeys(body) {
  return new Promise((res) => {
    const data = JSON.stringify(body);
    const r = http.request({ host: '127.0.0.1', port, path: '/api/internal/keys', method: 'POST', timeout: 4000,
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data), 'X-SV-Internal': TOKEN } }, (m) => { m.resume(); res(m.statusCode === 200); });
    r.on('error', () => res(false)); r.on('timeout', () => { r.destroy(); res(false); }); r.end(data);
  });
}

const freePort = () => new Promise((res, rej) => { const s = net.createServer(); s.on('error', rej); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });
const ping = (p) => new Promise((res) => { const r = http.get({ host: '127.0.0.1', port: p, path: '/api/state', timeout: 1500 }, (m) => { m.resume(); res(m.statusCode === 200); }); r.on('error', () => res(false)); r.on('timeout', () => { r.destroy(); res(false); }); });
const getJson = (p, u) => new Promise((res) => { http.get({ host: '127.0.0.1', port: p, path: u }, (m) => { let b = ''; m.on('data', (d) => b += d); m.on('end', () => { try { res(JSON.parse(b)); } catch { res(null); } }); }).on('error', () => res(null)); });

function killServer() {
  if (!server) return;
  const pid = server.pid; server = null;
  if (process.platform === 'win32') spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { stdio: 'ignore' }); else try { process.kill(-pid); } catch { /* gone */ }
}

async function startServer() {
  if (!fs.existsSync(PY)) {
    dialog.showErrorBox('SONIVERSE AI Clipper', 'The engine is not installed yet.\n\nRun  npm run setup  (or install.bat on Windows, ./install.sh on macOS / Linux) in:\n' + ROOT);
    app.quit(); return false;
  }
  port = await freePort();
  const logDir = path.join(ROOT, 'projects'); fs.mkdirSync(logDir, { recursive: true });
  const log = fs.openSync(path.join(logDir, 'ui_server.log'), 'a');
  server = spawn(PY, ['-m', 'clipper', 'serve', '--no-browser', '--port', String(port)], {
    cwd: ROOT, windowsHide: true, detached: process.platform !== 'win32', stdio: ['ignore', log, log],
    env: { ...process.env, ...(await loadKeys()), SV_INTERNAL_TOKEN: TOKEN, SV_NODE: process.execPath, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
  });
  server.on('exit', () => { if (!quitting && server) { server = null; dialog.showErrorBox('SONIVERSE AI Clipper', 'The engine stopped unexpectedly. See projects\\ui_server.log'); } });
  for (let i = 0; i < 160; i++) { if (await ping(port)) return true; await new Promise((r) => setTimeout(r, 250)); }
  dialog.showErrorBox('SONIVERSE AI Clipper', 'The engine did not start. See projects\\ui_server.log'); return false;
}

async function restartServer() {
  killServer(); await new Promise((r) => setTimeout(r, 600));
  if (await startServer() && win) win.loadURL(`http://127.0.0.1:${port}/`);
}

function createWindow() {
  win = new BrowserWindow({
    width: 1440, height: 920, minWidth: 1000, minHeight: 640, backgroundColor: '#0e0f13', title: 'SONIVERSE AI Clipper',
    icon: path.join(ROOT, 'assets', 'soniverse.ico'), autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  const local = (u) => u.startsWith(`http://127.0.0.1:${port}/`);
  win.webContents.setWindowOpenHandler(({ url }) => { if (/^https?:/.test(url) && !local(url)) shell.openExternal(url); return { action: 'deny' }; });
  win.webContents.on('will-navigate', (e, url) => { if (!local(url)) { e.preventDefault(); if (/^https?:/.test(url)) shell.openExternal(url); } });
  win.on('close', async (e) => {
    if (quitting) return;
    const st = await getJson(port, '/api/state');
    if (st && st.jobs && st.jobs.some((j) => j.status === 'running')) {
      const r = dialog.showMessageBoxSync(win, { type: 'warning', buttons: ['Keep running', 'Quit and stop jobs'], defaultId: 0, cancelId: 0, message: 'A clip job is still running.', detail: 'Quitting stops it (progress is cached, so a re-run resumes).' });
      if (r === 0) e.preventDefault();
    }
  });
  win.loadURL(`http://127.0.0.1:${port}/`);
}

const fromApp = (e) => e.senderFrame && e.senderFrame.url.startsWith(`http://127.0.0.1:${port}/`);
ipcMain.handle('pick-file', async (e) => {
  if (!fromApp(e)) return null;
  const r = await dialog.showOpenDialog(win, { title: 'Pick a gameplay / video file', properties: ['openFile'], filters: [{ name: 'Video', extensions: VIDEO }, { name: 'All files', extensions: ['*'] }] });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle('pick-folder', async (e) => {
  if (!fromApp(e)) return null;
  const r = await dialog.showOpenDialog(win, { title: 'Choose a folder', properties: ['openDirectory', 'createDirectory'] });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle('pick-gguf', async (e) => {
  if (!fromApp(e)) return null;
  // Electron's own native dialog - used instead of the dashboard's tkinter-based /api/browse fallback, which silently
  // does nothing on a Python build with no _tkinter (e.g. some bundled/portable interpreters ship without Tcl/Tk).
  const r = await dialog.showOpenDialog(win, { title: 'Pick a model file (.gguf)', properties: ['openFile'], filters: [{ name: 'GGUF model', extensions: ['gguf'] }, { name: 'All files', extensions: ['*'] }] });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle('key-status', (e) => { if (!fromApp(e)) return {}; const j = readKeyFile(), o = {}; for (const n of KEYS) o[n] = !!j[n]; for (const n of Object.keys(j)) if (isKey(n)) o[n] = !!j[n]; return o; });
ipcMain.handle('set-key', async (e, name, value) => {
  if (!fromApp(e) || !isKey(name) || typeof value !== 'string' || !value.trim()) return false;
  try { const blob = (await enc(value.trim())).toString('base64'); await writeKeys((j) => { j[name] = blob; }); } catch (err) { dialog.showErrorBox('Key not saved', String(err.message || err)); return false; }
  return pushKeys({ set: { [name]: value.trim() } });
});
ipcMain.handle('remove-key', async (e, name) => {
  if (!fromApp(e) || !isKey(name)) return false;
  try { await writeKeys((j) => { delete j[name]; }); } catch { return false; }
  return pushKeys({ clear: [name] });
});
// Reveal on demand for the Show button only (the renderer hides it again after 15 s). Never logged, never persisted outside safeStorage.
ipcMain.handle('reveal-key', async (e, name) => {
  if (!fromApp(e) || !isKey(name)) return null;
  const j = readKeyFile(); try { return j[name] ? await dec(j[name]) : null; } catch { return null; }
});

if (!app.requestSingleInstanceLock()) { app.quit(); } else {
  app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(async () => {
    Menu.setApplicationMenu(null);
    // macOS Dock icon: a BrowserWindow's `icon` option only sets the title-bar/alt-tab icon on mac, not the Dock -
    // that needs setting explicitly (matters most for this unpackaged dev run; a properly packaged .app would get
    // its Dock icon from the bundle's own Info.plist/icns instead).
    if (process.platform === 'darwin' && app.dock) { try { app.dock.setIcon(path.join(ROOT, 'assets', 'soniverse.png')); } catch { /* best effort */ } }
    if (await startServer()) createWindow();
  });
  app.on('before-quit', () => { quitting = true; killServer(); });
  app.on('window-all-closed', () => app.quit());
}
