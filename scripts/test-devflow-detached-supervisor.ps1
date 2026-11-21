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
[CmdletBinding()]
param([switch]$Run, [int]$MaxTasks = 1)
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
 $psi = [Diagnostics.ProcessStartInfo]::new()
 $psi.FileName = (Get-Command pwsh -ErrorAction Stop).Source
 $psi.WorkingDirectory = $repo
 $psi.UseShellExecute = $false
 foreach ($arg in @("-NoProfile", "-File", (Join-Path $scripts "start-devflow-detached.ps1"), "-Supervisor", "-RunId", "supervisor-loop-test", "-MaxTasks", "1", "-PollIntervalSeconds", "1", "-MaxCycles", "2")) {
  [void]$psi.ArgumentList.Add($arg)
 }
 $process = [Diagnostics.Process]::new()
 $process.StartInfo = $psi
 if (-not $process.Start()) { throw "Could not start isolated supervisor test process." }
 if (-not $process.WaitForExit(120000)) {
  try { $process.Kill($true) } catch {}
  throw "Detached supervisor regression timed out."
 }
 if ($process.ExitCode -ne 0) { throw "Supervisor did not recover successfully; exit=$($process.ExitCode)" }
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
 # A bounded run whose final cycle fails must be marked failed, not completed.
 Set-Content -LiteralPath (Join-Path $scripts "start-devflow-autopilot.ps1") -Value '[CmdletBinding()] param([switch]$Run,[int]$MaxTasks=1) exit 1'
 $failurePsi = [Diagnostics.ProcessStartInfo]::new()
 $failurePsi.FileName = (Get-Command pwsh -ErrorAction Stop).Source
 $failurePsi.WorkingDirectory = $repo
 $failurePsi.UseShellExecute = $false
 foreach ($arg in @("-NoProfile", "-File", (Join-Path $scripts "start-devflow-detached.ps1"), "-Supervisor", "-RunId", "supervisor-final-failure-test", "-MaxTasks", "1", "-PollIntervalSeconds", "1", "-MaxCycles", "1")) {
  [void]$failurePsi.ArgumentList.Add($arg)
 }
 $failureProcess = [Diagnostics.Process]::new()
 $failureProcess.StartInfo = $failurePsi
 if (-not $failureProcess.Start()) { throw "Could not start bounded failure-state test process." }
 if (-not $failureProcess.WaitForExit(120000)) {
  try { $failureProcess.Kill($true) } catch {}
  throw "Bounded failure-state regression timed out."
 }
 if ($failureProcess.ExitCode -ne 1) { throw "Expected failed bounded cycle to return exit 1, got $($failureProcess.ExitCode)." }
 $failureStatusPath = Join-Path (Join-Path $parent "repo-multiflow-logs") "supervisor-final-failure-test.status.json"
 $failureStatus = Get-Content -LiteralPath $failureStatusPath -Raw | ConvertFrom-Json
 if ($failureStatus.status -ne "failed" -or $failureStatus.last_exit_code -ne 1) {
  throw "Failed bounded cycle was not persisted as failed: $($failureStatus | ConvertTo-Json -Compress)"
 }
 try {
  $probe = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
  $probe.Dispose()
 } catch { throw "Scheduler lease remained locked after failed bounded run." }
 # Exercise the foreground mode used by Windows Task Scheduler, including automatic run-ID generation and per-cycle logs.
 Set-Content -LiteralPath (Join-Path $scripts "start-devflow-autopilot.ps1") -Value '[CmdletBinding()] param([switch]$Run,[int]$MaxTasks=1) Write-Output "foreground-cycle-ok"; exit 0'
 $foregroundPsi = [Diagnostics.ProcessStartInfo]::new()
 $foregroundPsi.FileName = (Get-Command pwsh -ErrorAction Stop).Source
 $foregroundPsi.WorkingDirectory = $repo
 $foregroundPsi.UseShellExecute = $false
 foreach ($arg in @("-NoProfile", "-File", (Join-Path $scripts "start-devflow-detached.ps1"), "-Supervisor", "-MaxTasks", "1", "-PollIntervalSeconds", "1", "-MaxCycles", "1")) {
  [void]$foregroundPsi.ArgumentList.Add($arg)
 }
 $foregroundProcess = [Diagnostics.Process]::new()
 $foregroundProcess.StartInfo = $foregroundPsi
 if (-not $foregroundProcess.Start()) { throw "Could not start foreground scheduled-task mode test process." }
 if (-not $foregroundProcess.WaitForExit(120000)) {
  try { $foregroundProcess.Kill($true) } catch {}
  throw "Foreground scheduled-task mode regression timed out."
 }
 if ($foregroundProcess.ExitCode -ne 0) { throw "Foreground scheduled-task mode failed with exit $($foregroundProcess.ExitCode)." }
 $foregroundRuns = @(Get-ChildItem -LiteralPath (Join-Path $parent "repo-multiflow-logs") -Filter "*.run.json" | ForEach-Object {
  $metadata = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
  if ($metadata.mode -eq "foreground-supervisor" -and $metadata.run_id -notin @("supervisor-loop-test", "supervisor-final-failure-test")) { $metadata }
 })
 if ($foregroundRuns.Count -ne 1) { throw "Expected one foreground supervisor run record, found $($foregroundRuns.Count)." }
 $foregroundRun = $foregroundRuns[0]
 $foregroundStatus = Get-Content -LiteralPath $foregroundRun.status_file -Raw | ConvertFrom-Json
 if ($foregroundStatus.status -ne "completed" -or $foregroundStatus.last_exit_code -ne 0) {
  throw "Foreground supervisor did not persist successful completion: $($foregroundStatus | ConvertTo-Json -Compress)"
 }
 if (-not (Test-Path -LiteralPath $foregroundStatus.last_stdout_log) -or -not (Test-Path -LiteralPath $foregroundStatus.last_stderr_log)) {
  throw "Foreground supervisor did not persist per-cycle stdout/stderr logs."
 }
 Write-Host "PASS: retry/backoff, terminal success/failure state, lease release, and foreground Task Scheduler mode with generated run ID and cycle logs."
} finally {
 Set-Location $oldLocation
 Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
 Remove-Item -LiteralPath (Join-Path $parent "repo-multiflow-state") -Recurse -Force -ErrorAction SilentlyContinue
 Remove-Item -LiteralPath (Join-Path $parent "repo-multiflow-logs") -Recurse -Force -ErrorAction SilentlyContinue
}
