// Start the app:   npm run dev   |   npm run web   |   npm run doctor   |   npm test
// or directly:     node scripts/run.mjs [desktop|web|doctor|test|cli ...args]
import path from 'node:path';
import { ROOT, VENV_PY, ELECTRON_DIR, step, warn, fail, venvReady, electronBin, run, runAsync, cyan } from './lib.mjs';

const [mode = 'desktop', ...rest] = process.argv.slice(2);
delete process.env.ELECTRON_RUN_AS_NODE;      // if it leaks in (e.g. from an IDE terminal) Electron would behave like plain Node and never open a window

if (!venvReady()) {
  console.log('First run: the Python environment is missing - running setup (a few minutes) ...');
  const code = await runAsync(process.execPath, [path.join(ROOT, 'scripts', 'setup.mjs')]);
  if (code !== 0 || !venvReady()) fail('Setup did not finish. Fix the message above and run:  npm run setup');
}

if (mode === 'desktop') {
  const el = electronBin();
  if (!el) {
    warn('The desktop app (Electron) is not installed - starting the browser dashboard instead. (npm run setup installs it.)');
    process.exit(await runAsync(VENV_PY, ['-m', 'clipper', 'serve']));
  }
  process.exit(await runAsync(el, ['.'], { cwd: ELECTRON_DIR, shell: process.platform === 'win32' }));
} else if (mode === 'web') {
  console.log(cyan('Browser dashboard - press Ctrl+C to stop.'));
  process.exit(await runAsync(VENV_PY, ['-m', 'clipper', 'serve', ...rest]));
} else if (mode === 'doctor') {
  process.exit(run(VENV_PY, ['-m', 'clipper', 'doctor', ...rest]));
} else if (mode === 'cli') {
  process.exit(run(VENV_PY, ['-m', 'clipper', ...rest]));
} else if (mode === 'test') {
  const dir = path.join(ROOT, 'tests');
  const files = rest.length ? rest : ['test_ai_chain.py', 'test_presets.py', 'test_system.py', 'test_facecam.py', 'test_openclipper.py'];
  let bad = 0;
  for (const f of files) { step(f); if (run(VENV_PY, [path.join(dir, f)]) !== 0) bad++; }
  process.exit(bad ? 1 : 0);
} else {
  fail(`Unknown mode "${mode}". Use: desktop | web | doctor | cli <args> | test`);
}
