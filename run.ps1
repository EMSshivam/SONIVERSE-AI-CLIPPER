# Start SONIVERSE AI Clipper from PowerShell:   .\run.ps1 [desktop|web|doctor|cli ...]      (default: desktop)
# Works on Windows PowerShell 5.1 and PowerShell 7 (also on macOS/Linux with pwsh).
param([Parameter(Position = 0)][string]$Mode = "desktop", [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
Set-Location $PSScriptRoot
if (Get-Command node -ErrorAction SilentlyContinue) {
  node scripts/run.mjs $Mode @Rest
  exit $LASTEXITCODE
}
$py = if ($IsWindows -or $env:OS -eq "Windows_NT") { ".\.venv\Scripts\python.exe" } else { "./.venv/bin/python" }
if (-not (Test-Path $py)) { Write-Host "Not installed yet - run .\install.ps1 first." -ForegroundColor Red; exit 1 }
switch ($Mode) {
  "doctor" { & $py -m clipper doctor }
  "cli" { & $py -m clipper @Rest }
  default { & $py -m clipper serve }
}
exit $LASTEXITCODE
