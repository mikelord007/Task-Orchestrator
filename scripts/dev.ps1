# Windows equivalent of `make dev`: backend on :8000, frontend on :3000.
# `make` is not installed on the Windows dev host; CI runs the Makefile on Linux.
#
#   pwsh scripts/dev.ps1

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

$backend = Start-Process -PassThru -NoNewWindow -WorkingDirectory $repo `
  -FilePath "uv" `
  -ArgumentList @("run", "--project", "backend", "python", "-m", "uvicorn",
                  "backend.app:app", "--reload", "--port", "8000")

Write-Host "backend  http://localhost:8000  (pid $($backend.Id))"
Write-Host "frontend http://localhost:3000"

try {
    Push-Location (Join-Path $repo "frontend")
    npm run dev
}
finally {
    Pop-Location
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
}
