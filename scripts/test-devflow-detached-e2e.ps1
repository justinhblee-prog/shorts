[CmdletBinding()]
param()
$ErrorActionPreference="Stop"
if($PSVersionTable.PSVersion.Major -lt 7){throw "PowerShell 7+ required."}
$source=(git rev-parse --show-toplevel 2>$null)
if($LASTEXITCODE -ne 0 -or -not $source){throw "Run from the repository checkout."}
$source=$source.Trim()
$temp=Join-Path ([IO.Path]::GetTempPath()) ("devflow-detached-e2e-"+[guid]::NewGuid().ToString("N"))
$repo=Join-Path $temp "checkout";$seed=Join-Path $temp "seed";$origin=Join-Path $temp "origin.git"
$bin=Join-Path $temp "bin";$worktrees=Join-Path $temp "checkout-worktrees"
$state=Join-Path $temp "checkout-multiflow-state";$logs=Join-Path $temp "checkout-multiflow-logs"
$oldPath=$env:PATH;$oldCommand=$env:DEVFLOW_AGENT_COMMAND;$oldArgs=$env:DEVFLOW_AGENT_ARGS_JSON
$pidSupervisor=$null;$statusPath=$null
try{
 New-Item -ItemType Directory -Force -Path $repo,$seed,$bin|Out-Null
 & git init --bare $origin|Out-Null
 & git -C $seed init|Out-Null
 & git -C $seed config user.name "Detached E2E Test"
 & git -C $seed config user.email "detached-e2e@example.invalid"
 New-Item -ItemType Directory -Force -Path (Join-Path $seed "scripts"),(Join-Path $seed ".devflow")|Out-Null
 foreach($name in @("start-devflow-autopilot.ps1","start-devflow-detached.ps1","git-cli-multiflow.ps1","git-cli-multiflow-parallel.ps1","git-cli-agent-config.ps1","devflow-agent-process.ps1")){
  Copy-Item (Join-Path $source "scripts/$name") (Join-Path $seed "scripts/$name")
 }
 Set-Content (Join-Path $seed "scripts/devflow.py") "raise SystemExit(0)" -Encoding utf8
 $manifest=@{schema_version=1;policy=@{max_parallel_worktrees=1;default_base="main";auto_merge=$false;auto_deploy=$false};tasks=@(@{id="BUILD-99010";title="detached end-to-end fixture";priority=1;status="ready";depends_on=@();scope=@("write a fixture output");acceptance=@("worker output exists")})}
 $manifest|ConvertTo-Json -Depth 20|Set-Content (Join-Path $seed ".devflow/tasks.json") -Encoding utf8
 & git -C $seed add -A
 & git -C $seed commit -m "detached e2e fixture"|Out-Null
 & git -C $seed branch -M main
 & git -C $seed remote add origin $origin
 & git -C $seed push -u origin main|Out-Null
 # A freshly initialized bare repository may still advertise an empty remote HEAD.
 & git --git-dir=$origin symbolic-ref HEAD refs/heads/main
 if($LASTEXITCODE -ne 0){throw "Could not set fixture bare-remote HEAD to main."}
 & git clone $origin $repo|Out-Null
 & git -C $repo config user.name "Detached E2E Test"
 & git -C $repo config user.email "detached-e2e@example.invalid"
 $ghLog=Join-Path $temp "gh-pr.log"
 $gh=@(
  "@echo off",
  'if "%1 %2"=="auth status" exit /b 0',
  'if "%1 %2"=="pr list" (echo [] & exit /b 0)',
  'if "%1 %2"=="pr create" (echo %*>>"%GH_TEST_LOG%" & exit /b 0)',
  "exit /b 0"
 ) -join [Environment]::NewLine
 Set-Content (Join-Path $bin "gh.cmd") $gh -Encoding ascii
 $agent=Join-Path $temp "fake-agent.ps1"
 Set-Content $agent 'param([string]$PromptFile) if(-not (Test-Path -LiteralPath $PromptFile)){throw "Prompt file missing"}; Set-Content -LiteralPath (Join-Path (Get-Location) "worker-output.txt") -Value "worker completed"' -Encoding utf8
 $env:PATH="$bin;$env:PATH";$env:GH_TEST_LOG=$ghLog
 $env:DEVFLOW_AGENT_COMMAND=$agent;$env:DEVFLOW_AGENT_ARGS_JSON='["{prompt_file}"]'
 Push-Location $repo
 try{
  $launch=& pwsh -NoProfile -File (Join-Path $repo "scripts/start-devflow-detached.ps1") -MaxTasks 1 -MaxCycles 1 2>&1
  if($LASTEXITCODE -ne 0){throw "Detached supervisor launch failed: $($launch -join [Environment]::NewLine)"}
 }finally{Pop-Location}
 $deadline=[DateTime]::UtcNow.AddSeconds(90);$status=$null;$run=$null
 do{
  Start-Sleep -Milliseconds 250
  $meta=@(Get-ChildItem $logs -Filter "*.run.json" -ErrorAction SilentlyContinue|Sort-Object LastWriteTime -Descending|Select-Object -First 1)
  if($meta){$run=Get-Content $meta[0].FullName -Raw|ConvertFrom-Json;$statusPath=[string]$run.status_file;if(Test-Path $statusPath){$status=Get-Content $statusPath -Raw|ConvertFrom-Json}}
 }while([DateTime]::UtcNow -lt $deadline -and (-not $status -or $status.status -notin @("completed","failed","failed_to_start")))
 if(-not $status -or $status.status -ne "completed" -or $status.last_exit_code -ne 0){
  $err=if($run -and (Test-Path $run.stderr_log)){Get-Content $run.stderr_log -Raw}else{"<no supervisor stderr>"}
  $out=if($run -and (Test-Path $run.stdout_log)){Get-Content $run.stdout_log -Raw}else{"<no supervisor stdout>"}
  throw "Detached E2E supervisor failed. status=$($status.status); stdout=$out; stderr=$err"
 }
 $stateFile=Join-Path $state "state.json"
 if(-not(Test-Path $stateFile)){throw "Worker state file was not created."}
 $stateData=Get-Content $stateFile -Raw|ConvertFrom-Json
 if($stateData.tasks."BUILD-99010".status -ne "draft_pr_created"){throw "Worker did not reach draft_pr_created: $($stateData.tasks."BUILD-99010".status)"}
 if(-not(Test-Path $ghLog)){throw "Fake GitHub CLI did not receive Draft PR creation."}
 $ghCalls=Get-Content $ghLog -Raw
 if($ghCalls -notmatch "--draft" -or $ghCalls -notmatch "BUILD-99010"){throw "Draft PR command did not include the task ID and --draft."}
 $remote=& git -C $repo ls-remote --heads origin "autopilot/build-99010-*"
 if($LASTEXITCODE -ne 0 -or -not $remote){throw "Worker branch was not pushed to the fixture remote."}
 $lease=$null
 try{$lease=[IO.File]::Open((Join-Path $state "scheduler.lock"),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
 catch{throw "Scheduler lease was not released after successful end-to-end run."}
 finally{if($lease){$lease.Dispose()}}
 Write-Host "PASS: detached supervisor -> task discovery -> isolated worktree -> .ps1 Agent CLI -> validation -> commit/push -> Draft PR -> state persistence."
}finally{
 if($pidSupervisor){$p=Get-Process -Id $pidSupervisor -ErrorAction SilentlyContinue;if($p){try{$p.Kill()}catch{}}}
 $env:PATH=$oldPath
 Remove-Item Env:GH_TEST_LOG -ErrorAction SilentlyContinue
 if($null -eq $oldCommand){Remove-Item Env:DEVFLOW_AGENT_COMMAND -ErrorAction SilentlyContinue}else{$env:DEVFLOW_AGENT_COMMAND=$oldCommand}
 if($null -eq $oldArgs){Remove-Item Env:DEVFLOW_AGENT_ARGS_JSON -ErrorAction SilentlyContinue}else{$env:DEVFLOW_AGENT_ARGS_JSON=$oldArgs}
 if(Test-Path $temp){Remove-Item -LiteralPath $temp -Recurse -Force}
}
