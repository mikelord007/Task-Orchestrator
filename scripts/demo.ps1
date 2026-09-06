# Windows equivalent of `make demo`: preflight -> domain-a -> domain-b -> summary
# (scripts/demo_run.py). Needs the backend already running in another terminal
# (scripts/dev.ps1 or `uv run --project backend python -m uvicorn backend.app:app`)
# and a populated .env (LLM + GitHub credentials, see .env.example).
#
#   pwsh scripts/demo.ps1 [-AgentId <id>]
#
# -AgentId reuses an existing Domain A agent instead of creating a new one
# (idempotent re-runs).

param(
    [string]$AgentId
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$demoRun = Join-Path $repo "scripts" "demo_run.py"

$demoArgs = @("run", "--project", "backend", "python", $demoRun, "demo")
if ($AgentId) {
    $demoArgs += @("--agent-id", $AgentId)
}

& uv @demoArgs
