# SONIVERSE AI Clipper - one-click setup for Windows. No Node.js, Python, FFmpeg, winget or admin rights needed beforehand:
#   1. uv (a small, signed-by-checksum Python installer) -> a private Python 3.12 + .venv in this folder
#   2. the AI libraries (+ NVIDIA CUDA libraries only when an NVIDIA GPU is present)
#   3. portable FFmpeg + the Electron desktop window + the Whisper model and smart-reframing engine for THIS computer
# Safe to run again: it only fetches what is missing. Everything stays inside this folder (plus the shared model cache in your user profile).
param([string]$Root = "", [switch]$WithOllama, [switch]$NoElectron, [switch]$NoModels, [switch]$NoShortcut)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"                      # Windows PowerShell 5.1 downloads are 10x slower with the progress bar
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}
if (-not $Root) { $Root = Split-Path -Parent $PSScriptRoot }
Set-Location $Root
function Say($m, $c = "Cyan") { Write-Host "`n=== $m" -ForegroundColor $c }
function Fail($m) { Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }
if ($Root.Length -gt 90) {
  Write-Host "WARNING: this folder path is long ($($Root.Length) characters). Windows limits file paths to 260 characters and some AI libraries have deep folders, so setup can fail." -ForegroundColor Yellow
  Write-Host "         If it does, move this folder to a short path such as C:\SONIVERSE and start it again." -ForegroundColor Yellow
}
$env:UV_LINK_MODE = "copy"                                   # no hard-link warnings, works across drives

# ---------------------------------------------------------------------------------------------- 1. uv
Say "1/4  Python (private copy, nothing is installed system-wide)"
$tools = Join-Path $Root "tools"; $uvDir = Join-Path $tools "uv"; $uv = Join-Path $uvDir "uv.exe"
if (-not (Test-Path $uv)) {
  $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64" } else { "x86_64" }
  # Pinned release + SHA256 written here (not fetched from the same server as the zip), so a tampered download is always rejected.
  $uvVersion = "0.13.9"
  $uvHash = @{ "x86_64" = "edd61f7f5728a56cc62455386661860bdfc7bab65872f39b0c25bdcc1d8e1beb"; "aarch64" = "72eed595983a4d7d22d79f21065b0f4479cc7e5c7a89104bb410c8f47559a878" }
  $name = "uv-$arch-pc-windows-msvc.zip"; $base = "https://github.com/astral-sh/uv/releases/download/$uvVersion"
  New-Item -ItemType Directory -Force -Path $uvDir | Out-Null
  $zip = Join-Path $env:TEMP $name
  Write-Host "Downloading uv $uvVersion ($name) ..."
  try { Invoke-WebRequest "$base/$name" -OutFile $zip -UseBasicParsing } catch { Fail "Could not download uv. Check your internet connection / proxy, then run this again.`n$_" }
  $got = (Get-FileHash $zip -Algorithm SHA256).Hash
  if ($got -ne $uvHash[$arch]) { Remove-Item $zip -Force; Fail "uv download failed its SHA256 check - not installing it. Try again." }
  Write-Host "uv: SHA256 checksum OK"
  Expand-Archive -Path $zip -DestinationPath $uvDir -Force; Remove-Item $zip -Force
  if (-not (Test-Path $uv)) { $f = Get-ChildItem $uvDir -Recurse -Filter uv.exe | Select-Object -First 1; if ($f) { Move-Item $f.FullName $uv -Force } }
  if (-not (Test-Path $uv)) { Fail "uv.exe was not found in the download." }
}
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "Creating the Python environment (downloads Python 3.12 once if you do not have it) ..."
  & $uv venv --seed --python 3.12 (Join-Path $Root ".venv")
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $py)) { Fail "Could not create the Python environment." }
}

# ---------------------------------------------------------------------------------------------- 2. packages
Say "2/4  AI libraries (a few minutes the first time)"
& $uv pip install --python $py -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "Installing the Python packages failed (see the messages above). Check your internet connection and run this again." }
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
  Write-Host "NVIDIA GPU found: adding the CUDA libraries so Whisper runs on the GPU"
  & $uv pip install --python $py -r (Join-Path $Root "requirements-cuda.txt")
  & $uv pip install --python $py --upgrade ctranslate2
} else { Write-Host "No NVIDIA GPU found: CPU mode (works everywhere, just slower on long videos; models are chosen to suit this PC)." -ForegroundColor Yellow }
foreach ($d in "input", "output", "cache", "projects", "assets\models") { New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null }
$lc = Join-Path $Root "config.local.yaml"
if (-not (Test-Path $lc)) { "# Your overrides (see config.yaml for every option). Example:`n# ai: {provider: local}`n" | Set-Content $lc -Encoding UTF8 }
$mp = Join-Path $Root "assets\models\blaze_face_short_range.tflite"
if (-not (Test-Path $mp)) {
  try { Invoke-WebRequest "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite" -OutFile $mp -UseBasicParsing }
  catch { Write-Host "Could not download the face model (face tracking falls back to OpenCV - still works)." -ForegroundColor Yellow }
}

# ---------------------------------------------------------------------------------------------- 3. FFmpeg, Electron, models
Say "3/4  FFmpeg, desktop window, models for this computer"
$a = @("scripts\bootstrap_tools.py", "--root", $Root)
if ($NoElectron) { $a += "--no-electron" }
if ($NoModels) { $a += "--no-models" }
if ($WithOllama) { $a += "--with-ollama" }
& $py @a
if ($LASTEXITCODE -ne 0) { Fail "FFmpeg could not be set up. Install it manually (winget install Gyan.FFmpeg) and run this again." }

# ---------------------------------------------------------------------------------------------- 4. shortcut
Say "4/4  Desktop shortcut"
if (-not $NoShortcut -and $env:SV_NO_SHORTCUT -ne "1") {
  try {
    $bat = Join-Path $Root "SONIVERSE AI Clipper.bat"; $desk = [Environment]::GetFolderPath("Desktop")
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut((Join-Path $desk "SONIVERSE AI Clipper.lnk"))
    $lnk.TargetPath = $bat; $lnk.WorkingDirectory = $Root; $lnk.IconLocation = (Join-Path $Root "assets\soniverse.ico")
    $lnk.WindowStyle = 7; $lnk.Description = "SONIVERSE AI Clipper - local AI Shorts/Reels maker"; $lnk.Save()
    Write-Host "Desktop shortcut created."
  } catch { Write-Host "Could not create a Desktop shortcut (not important): $_" -ForegroundColor Yellow }
}
Say "Setup finished." "Green"
exit 0
