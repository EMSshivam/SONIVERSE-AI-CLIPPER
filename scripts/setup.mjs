// One-command setup:  npm run setup      (Windows, macOS, Linux)
// Flags: --no-electron  skip the desktop shell (browser dashboard only)   --no-openclipper  skip the optional smart-reframing engine
//        --no-models    do not download the Whisper model now (it downloads on first use)   --with-ollama  also set up the local vision model that suits this PC
//        --cpu          never install the NVIDIA CUDA libraries            --cuda  force-install them
// Safe to re-run. Touches only this folder.
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, IS_WIN, IS_MAC, VENV, VENV_PY, ELECTRON_DIR, step, ok, warn, fail, yellow, cyan, probe, run, have, findPython, venvReady, hasNvidia, ffmpegHint, ffmpegPresent, brandElectronMac } from './lib.mjs';

const flags = new Set(process.argv.slice(2));
const nodeMajor = +process.versions.node.split('.')[0];
if (nodeMajor < 18) fail(`Node.js ${process.versions.node} is too old - install Node 18 or newer (https://nodejs.org).`);

step('1/6  Python 3.10 - 3.13');
const py = findPython();
if (!py) {
  fail('No suitable Python found.\n  Install Python 3.12:  ' + (IS_WIN ? 'winget install Python.Python.3.12' : IS_MAC ? 'brew install python@3.12' : 'sudo apt install python3 python3-venv python3-pip') + '\n  then run  npm run setup  again.');
}
ok(`using ${py.cmd} ${py.args.join(' ')}`.trim());

step('2/6  FFmpeg');
if (ffmpegPresent()) ok('ffmpeg found');
else warn('ffmpeg was not found. Install it, then re-run setup (or just start the app: it has an "Install FFmpeg" button on Windows/macOS):\n        ' + ffmpegHint());

step('3/6  Python environment (.venv) + packages');
if (!venvReady()) {
  if (run(py.cmd, [...py.args, '-m', 'venv', VENV]) !== 0) fail('Could not create the virtual environment' + (!IS_WIN && !IS_MAC ? ' (on Debian/Ubuntu: sudo apt install python3-venv)' : '') + '.');
}
const pip = (...a) => run(VENV_PY, ['-m', 'pip', ...a]);
pip('install', '--upgrade', 'pip');
if (pip('install', '-r', 'requirements.txt') !== 0) fail('pip could not install requirements.txt (see the messages above).');
const nvidia = flags.has('--cuda') || (!flags.has('--cpu') && hasNvidia());
if (nvidia) {
  console.log(cyan('  NVIDIA GPU detected -> installing the CUDA libraries for GPU Whisper'));
  if (pip('install', '-r', 'requirements-cuda.txt') !== 0) warn('CUDA libraries failed to install - Whisper will fall back to the CPU.');
  pip('install', '--upgrade', 'ctranslate2');   // newest build first: older ones have no RTX 50-series (Blackwell) kernels
} else {
  ok('no NVIDIA GPU (or --cpu): CPU mode. Models are chosen automatically to suit this computer.');
}

step('4/6  Folders and config');
for (const d of ['input', 'output', 'cache', 'projects', path.join('assets', 'models')]) fs.mkdirSync(path.join(ROOT, d), { recursive: true });
const local = path.join(ROOT, 'config.local.yaml');
if (!fs.existsSync(local)) fs.writeFileSync(local, '# Your overrides (see config.yaml for every option). Example:\n# ai: {provider: local}\n');
const envEx = path.join(ROOT, '.env'), envSrc = path.join(ROOT, '.env.example');
if (!fs.existsSync(envEx) && fs.existsSync(envSrc)) { fs.copyFileSync(envSrc, envEx); ok('created .env (put API keys there if you do not use the desktop app)'); }
const mp = path.join(ROOT, 'assets', 'models', 'blaze_face_short_range.tflite');
if (!fs.existsSync(mp)) {
  try {
    const r = await fetch('https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    fs.writeFileSync(mp, Buffer.from(await r.arrayBuffer())); ok('face-tracking model downloaded');
  } catch (e) { warn('could not download the face model (' + e.message + '). Face tracking falls back to OpenCV - still works.'); }
}

step('5/6  Desktop app (Electron) - optional');
if (flags.has('--no-electron')) ok('skipped (--no-electron): use  npm run web  for the browser dashboard');
else if (!have('npm', ['--version'])) warn('npm not found - skipping the desktop app. The browser dashboard works:  npm run web');
else {
  const code = run('npm', ['install', '--no-audit', '--no-fund'], { cwd: ELECTRON_DIR, shell: IS_WIN });
  if (code !== 0) warn('Electron did not install - use the browser dashboard:  npm run web');
  else { brandElectronMac(); ok('desktop app ready'); }
}

step('6/6  Models and engines for THIS computer (Whisper model, OpenClipper' + (flags.has('--with-ollama') ? ', local vision model' : '') + ')');
{
  const a = ['-m', 'clipper', 'setup-all'];
  if (flags.has('--with-ollama')) a.push('--ollama');
  if (flags.has('--no-openclipper')) a.push('--skip-openclipper');
  if (flags.has('--no-models')) a.push('--skip-whisper');
  if (run(VENV_PY, a) !== 0) warn('some optional parts did not install - the app still works; retry from Settings > Setup (one button).');
}

step('Hardware report');
run(VENV_PY, ['-m', 'clipper', 'doctor']);
console.log('\n' + yellow('Done. ') + 'Start the app with:  ' + cyan('npm run dev') + '   (desktop)   or   ' + cyan('npm run web') + '   (browser)');
console.log('First clip? Drop a recording into the input/ folder, open the app and press Start. Full guide: README.md');
