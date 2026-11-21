[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
$source = Join-Path $PSScriptRoot "start-devflow-detached.ps1"
if (-not (Test-Path -LiteralPath $source)) { throw "Detached supervisor script not found: $source" }
$temp = Join-Path ([IO.Path]::GetTempPath()) ("devflow-supervisor-test-" + [guid]::NewGuid().ToString("N"))
$repo = Join-Path $temp "repo"
$scripts = Join-Path $repo "scripts"
$parent = Split-Path $repo -Parent
$oldLocation = Get-Location
try {
 New-Item -ItemType Directory -Force -Path $scripts | Out-Null
 & git init --quiet $repo
 if ($LASTEXITCODE -ne 0) { throw "Could not initialize temporary Git repository." }
 & git -C $repo config user.name "DevFlow Test"
 & git -C $repo config user.email "devflow-test@example.invalid"
 Copy-Item -LiteralPath $source -Destination (Join-Path $scripts "start-devflow-detached.ps1")
 Set-Content -LiteralPath (Join-Path $scripts "git-cli-agent-config.ps1") -Value 'param([switch]$Check)'
 $counter = Join-Path $scripts "cycle-count.txt"
 $stub = @'
$count = 0
$counter = Join-Path $PSScriptRoot "cycle-count.txt"
if (Test-Path $counter) { $count = [int](Get-Content $counter -Raw) }
$count++
Set-Content -LiteralPath $counter -Value $count
# Fail the first cycle to prove the detached supervisor recovers and retries.
if ($count -eq 1) { exit 1 }
exit 0
'@
 Set-Content -LiteralPath (Join-Path $scripts "start-devflow-autopilot.ps1") -Value $stub
 Set-Location $repo
 & (Join-Path $scripts "start-devflow-detached.ps1") -Supervisor -RunId "supervisor-loop-test" -MaxTasks 1 -PollIntervalSeconds 1 -MaxCycles 2
 if ($LASTEXITCODE -ne 0) { throw "Supervisor did not recover successfully; exit=$LASTEXITCODE" }
 $cycles = [int](Get-Content -LiteralPath $counter -Raw)
 if ($cycles -ne 2) { throw "Expected exactly two scheduler cycles, observed $cycles." }
 $statusPath = Join-Path (Join-Path $parent "repo-multiflow-logs") "supervisor-loop-test.status.json"
 $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
 if ($status.status -ne "completed" -or $status.cycle -ne 2 -or $status.consecutive_failures -ne 0) {
  throw "Unexpected terminal scheduler state: $($status | ConvertTo-Json -Compress)"
 }
 $lockPath = Join-Path (Join-Path $parent "repo-multiflow-state") "scheduler.lock"
 try {
  $probe = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
  $probe.Dispose()
 } catch { throw "Supervisor scheduler lease remained locked after completion." }
 Write-Host "PASS: detached supervisor retried a failed cycle, completed the next cycle, persisted terminal state, and released its scheduler lease."
} finally {
 Set-Location $oldLocation
 Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
 Remove-Item -LiteralPath (Join-Path $parent "repo-multiflow-state") -Recurse -Force -ErrorAction SilentlyContinue
 Remove-Item -LiteralPath (Join-Path $parent "repo-multiflow-logs") -Recurse -Force -ErrorAction SilentlyContinue
}
