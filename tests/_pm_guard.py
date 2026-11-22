"""Safety net for tests that exercise install_docker() / ollama_ctl.install() / tools_setup.install_ffmpeg(): these fake a package
manager (winget / brew) by putting a script of that name first on PATH. If a test's PATH scoping has a bug and the REAL package
manager is still reachable (e.g. a dev Mac with actual Homebrew installed), that real binary must never run - it would really
install software on whoever's machine is running the tests.

`guard()` monkeypatches subprocess.Popen for the rest of the process: any call whose argv[0] basename is a real package-manager
name is let through only if it resolves to a path under a temp directory (where tests put their FAKE scripts); a path outside
that (the real system install) raises instead of running. Call this once, near the top of a test file, before anything that
might invoke install_docker / ollama_ctl.install / tools_setup.install_ffmpeg."""
import pathlib
import subprocess

_BLOCK_NAMES = {"brew", "winget"}
_REAL_POPEN = subprocess.Popen


def _is_fake_path(p: pathlib.Path) -> bool:
    s = str(p)
    return "/private/var/folders" in s or "/var/folders" in s or "/tmp/" in s or s.startswith("/tmp")


def _guarded_popen(cmd, *a, **k):
    exe = cmd[0] if isinstance(cmd, (list, tuple)) else cmd
    name = pathlib.Path(str(exe)).name
    if name in _BLOCK_NAMES:
        resolved = pathlib.Path(str(exe)).resolve()
        if not _is_fake_path(resolved):
            raise RuntimeError(f"pm-guard: refusing to run a REAL package manager in a test: {cmd!r} (resolved to {resolved}). "
                                "This test should only ever reach a FAKE script under a temp dir - fix its PATH scoping.")
    return _REAL_POPEN(cmd, *a, **k)


def guard():
    subprocess.Popen = _guarded_popen
