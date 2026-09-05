# Windows equivalent of `make test`.
#   pwsh scripts/test.ps1

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

# cd into backend/ so pytest's testpaths (tests, ../evaluators, ../scripts) resolve.
Push-Location (Join-Path $repo "backend")
try {
    uv run python -m pytest
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}
