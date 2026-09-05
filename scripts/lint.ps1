# Windows equivalent of `make lint`: ruff check + ruff format --check + tsc.
#   pwsh scripts/lint.ps1

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

Push-Location $repo
try {
    uv run --project backend ruff check backend contracts scripts
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    uv run --project backend ruff format --check backend contracts scripts
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Push-Location (Join-Path $repo "frontend")
    try {
        npx tsc --noEmit
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally { Pop-Location }
}
finally {
    Pop-Location
}
