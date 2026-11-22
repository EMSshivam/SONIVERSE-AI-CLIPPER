// Shared helpers for scripts/setup.mjs and scripts/run.mjs. Plain Node (>=18), no dependencies, works on Windows / macOS / Linux.
import { spawnSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const IS_WIN = process.platform === 'win32';
export const IS_MAC = process.platform === 'darwin';
export const VENV = path.join(ROOT, '.venv');
export const VENV_PY = IS_WIN ? path.join(VENV, 'Scripts', 'python.exe') : path.join(VENV, 'bin', 'python');
export const ELECTRON_DIR = path.join(ROOT, 'electron');

const c = (n) => (s) => (process.stdout.isTTY ? `\x1b[${n}m${s}\x1b[0m` : s);
export const cyan = c(36), green = c(32), yellow = c(33), red = c(31), dim = c(2);
export const step = (m) => console.log('\n' + cyan('=== ' + m));
export const ok = (m) => console.log(green('  ok  ') + m);
export const warn = (m) => console.log(yellow(' warn ') + m);
export const fail = (m) => { console.error(red('ERROR ') + m); process.exit(1); };

/** Run a command, return {status, stdout}. Never throws. */
export function probe(cmd, args = [], opts = {}) {
  try {
    const r = spawnSync(cmd, args, { encoding: 'utf8', timeout: opts.timeout ?? 15000, shell: opts.shell ?? false, cwd: opts.cwd, env: opts.env ?? process.env });
    return { status: r.status ?? 1, stdout: (r.stdout || '') + (r.stderr || ''), error: r.error };
  } catch (e) { return { status: 1, stdout: '', error: e }; }
}

/** Run a command with the terminal attached; returns the exit code. */
export function run(cmd, args = [], opts = {}) {
  const r = spawnSync(cmd, args, { stdio: 'inherit', cwd: opts.cwd ?? ROOT, env: opts.env ?? process.env, shell: opts.shell ?? false });
  return r.status ?? 1;
}

/** Like run() but keeps running asynchronously (Ctrl+C is forwarded); resolves with the exit code. */
export function runAsync(cmd, args = [], opts = {}) {
  return new Promise((res) => {
    const p = spawn(cmd, args, { stdio: 'inherit', cwd: opts.cwd ?? ROOT, env: opts.env ?? process.env, shell: opts.shell ?? false });
    p.on('exit', (code) => res(code ?? 0)); p.on('error', () => res(1));
  });
}

export const have = (cmd, args = ['--version']) => probe(cmd, args, { shell: IS_WIN }).status === 0;

/** A Python 3.10-3.13 interpreter: -> {cmd, args} to invoke it, or null. */
export function findPython() {
  const wanted = (out) => { const m = out.match(/(\d+)\.(\d+)/); return m && +m[1] === 3 && +m[2] >= 10 && +m[2] <= 13; };
  const cands = [];
  if (IS_WIN) for (const v of ['3.12', '3.11', '3.13', '3.10']) cands.push({ cmd: 'py', args: ['-' + v] });
  for (const v of ['3.12', '3.11', '3.13', '3.10']) cands.push({ cmd: 'python' + v, args: [] });
  cands.push({ cmd: 'python3', args: [] }, { cmd: 'python', args: [] });
  for (const k of cands) {
    const r = probe(k.cmd, [...k.args, '-c', 'import sys;print("%d.%d" % sys.version_info[:2])']);
    if (r.status === 0 && wanted(r.stdout)) return k;
  }
  return null;
}

export const venvReady = () => fs.existsSync(VENV_PY);

/** Is there an NVIDIA GPU with a working driver? */
export const hasNvidia = () => probe('nvidia-smi', ['--query-gpu=name', '--format=csv,noheader']).status === 0;

export function ffmpegHint() {
  if (IS_MAC) return 'brew install ffmpeg      (Homebrew: https://brew.sh)';
  if (IS_WIN) return 'winget install Gyan.FFmpeg      (or https://www.gyan.dev/ffmpeg/builds/ -> release essentials, add to PATH)';
  return 'sudo apt install ffmpeg      (Debian/Ubuntu)   |   sudo dnf install ffmpeg   |   sudo pacman -S ffmpeg';
}

export function ffmpegPresent() {
  if (have('ffmpeg', ['-version'])) return true;
  if (IS_MAC) return ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg'].some((p) => fs.existsSync(p));
  return false;
}

export function electronBin() {
  // 1) the binary the one-click launcher downloaded (works without Node/npm)   2) the npm shim (developers who ran `npm install`)
  const dist = path.join(ELECTRON_DIR, 'node_modules', 'electron', 'dist');
  const direct = path.join(dist, IS_WIN ? 'electron.exe' : IS_MAC ? 'Electron.app/Contents/MacOS/Electron' : 'electron');
  if (fs.existsSync(direct)) return direct;
  const b = path.join(ELECTRON_DIR, 'node_modules', '.bin', IS_WIN ? 'electron.cmd' : 'electron');
  return fs.existsSync(b) ? b : null;
}
