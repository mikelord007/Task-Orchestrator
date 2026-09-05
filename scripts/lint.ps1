# Windows equivalent of `make lint`: ruff check + ruff format --check (backend-only;
# W5 owns frontend/ and its own tsc lint step).
#   pwsh scripts/lint.ps1

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

Push-Location $repo
try {
    uv run --project backend ruff check backend contracts scripts evaluators agents
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    uv run --project backend ruff format --check backend contracts scripts evaluators agents
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}
