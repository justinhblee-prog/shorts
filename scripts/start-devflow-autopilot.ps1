[CmdletBinding()]
param(
    [string]$Task = "BUILD-00352",
    [string]$Base = "feat/ffmpeg-render-execution-guard-2026-11-20",
    [switch]$Parallel,
    [ValidateRange(1, 3)]
    [int]$MaxParallel = 3
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot
try {
    foreach ($tool in @("git", "python", "gh")) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            throw "Required command not found on PATH: $tool"
        }
    }

    $status = git status --porcelain
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect Git working-tree status." }
    if ($status) {
        throw "Working tree is not clean. Commit or stash changes before unattended execution."
    }

    gh auth status *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub CLI is not authenticated. Run 'gh auth login' first."
    }

    if (-not $env:DEVFLOW_AGENT_COMMAND_JSON) {
        if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
            throw "No coding agent configured. Install/authenticate Codex CLI or set DEVFLOW_AGENT_COMMAND_JSON to a JSON argv array."
        }
        $env:DEVFLOW_AGENT_COMMAND_JSON = '["codex","exec","--full-auto"]'
    }

    $env:DEVFLOW_BASE = $Base
    Write-Host "[NEXUS] Base: $Base"
    if ($Parallel) {
        python (Join-Path $PSScriptRoot "devflow_parallel.py") --max-parallel $MaxParallel --base $Base
    }
    else {
        python (Join-Path $PSScriptRoot "devflow_autopilot.py") --task $Task --base $Base
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Devflow automation exited with code $LASTEXITCODE. Inspect the retained worktree and logs."
    }
    Write-Host "[NEXUS] Automation flow completed. Review the generated Draft PR; nothing was merged or deployed."
}
finally {
    Pop-Location
}
