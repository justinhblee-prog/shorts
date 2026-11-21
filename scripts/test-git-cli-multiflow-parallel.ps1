[CmdletBinding()]
param()
$ErrorActionPreference="Stop"
$originalPath=$env:PATH
if($PSVersionTable.PSVersion.Major -lt 7){throw "PowerShell 7+ required."}
$repoRoot=(git rev-parse --show-toplevel 2>$null)
if($LASTEXITCODE -ne 0 -or -not $repoRoot){throw "Run from the repository checkout."}
$engineSource=Join-Path $repoRoot "scripts/git-cli-multiflow-parallel.ps1"
$agentProcessHelper=Join-Path $repoRoot "scripts/devflow-agent-process.ps1"
$temp=Join-Path ([IO.Path]::GetTempPath()) ("devflow-parallel-test-"+[guid]::NewGuid().ToString("N"))
$origin=Join-Path $temp "origin.git";$seed=Join-Path $temp "seed";$checkout=Join-Path $temp "checkout"
$bin=Join-Path $temp "bin";$state=Join-Path $temp "state"
New-Item -ItemType Directory -Force -Path $temp,$bin|Out-Null
try{
 & git init --bare $origin|Out-Null
 & git init $seed|Out-Null
 & git -C $seed config user.name "Multiflow Test"
 & git -C $seed config user.email "multiflow-test@example.invalid"
 New-Item -ItemType Directory -Force -Path (Join-Path $seed "scripts"),(Join-Path $seed ".devflow")|Out-Null
 Copy-Item $engineSource (Join-Path $seed "scripts/git-cli-multiflow-parallel.ps1")
 Copy-Item $agentProcessHelper (Join-Path $seed "scripts/devflow-agent-process.ps1")
 Set-Content (Join-Path $seed "scripts/devflow.py") "from pathlib import Path; Path(__file__).resolve().parents[1].joinpath('.validator-ran').write_text('ok', encoding='utf-8')" -Encoding utf8
 $manifest=@{
  policy=@{default_base="main";max_parallel_worktrees=3;auto_merge=$false;auto_deploy=$false}
  tasks=@(
   @{id="BUILD-99001";title="parallel fixture A";status="ready";priority=1;depends_on=@();scope=@("write an isolated marker");acceptance=@("marker exists")},
   @{id="BUILD-99002";title="parallel fixture B";status="ready";priority=2;depends_on=@();scope=@("write an isolated marker");acceptance=@("marker exists")},
   @{id="BUILD-99003";title="parallel fixture C";status="ready";priority=3;depends_on=@();scope=@("write an isolated marker");acceptance=@("marker exists")},
   @{id="BUILD-99004";title="dependent fixture D";status="ready";priority=4;depends_on=@("BUILD-99001");scope=@("must remain gated");acceptance=@("must not run before dependency completion")},
   @{id="BUILD-99005";title="open PR duplicate fixture E";status="ready";priority=5;depends_on=@();scope=@("must be skipped by open PR metadata");acceptance=@("must not be dispatched when an open PR body references this task ID")}
  )
 }
 $manifest|ConvertTo-Json -Depth 20|Set-Content (Join-Path $seed ".devflow/tasks.json") -Encoding utf8
 & git -C $seed add -A
 & git -C $seed commit -m "test fixture"
 & git -C $seed branch -M main
 & git -C $seed remote add origin $origin
 & git -C $seed push -u origin main
 & git --git-dir=$origin symbolic-ref HEAD refs/heads/main
 & git clone $origin $checkout|Out-Null
 & git -C $checkout config user.name "Multiflow Test"
 & git -C $checkout config user.email "multiflow-test@example.invalid"
 $fakeGh=@(
  "@echo off",
  'if "%1 %2"=="pr list" (echo [{"title":"Timeline integration","body":"Implements BUILD-99005","headRefName":"feat/timeline-integration","baseRefName":"main"}] & exit /b 0)',
  'if "%1 %2"=="pr create" (echo https://example.invalid/draft & exit /b 0)',
  'if "%1 %2"=="auth status" exit /b 0',
  "exit /b 0"
 ) -join [Environment]::NewLine
 Set-Content (Join-Path $bin "gh.cmd") $fakeGh -Encoding ascii
 $agent=Join-Path $temp "fake-agent.ps1"
 $agentCode=@'
param([string]$Prompt)
$log=$env:DEVFLOW_TEST_LOG
$start=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
if($env:GH_TOKEN){Add-Content -LiteralPath $log -Value "credential-leak|$start|$PID"}else{Add-Content -LiteralPath $log -Value "credential-isolated|$start|$PID"}
Add-Content -LiteralPath $log -Value "start|$start|$PID"
Start-Sleep -Seconds 5
$marker=Join-Path (Get-Location) ("worker-"+$PID+".txt")
Set-Content -LiteralPath $marker -Value $Prompt -Encoding utf8
$end=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
Add-Content -LiteralPath $log -Value "end|$end|$PID"
'@
 Set-Content -LiteralPath $agent -Value $agentCode -Encoding utf8
 $log=Join-Path $temp "agent.log";$env:DEVFLOW_TEST_LOG=$log
 $env:PATH="$bin;$env:PATH"
 $env:DEVFLOW_AGENT_COMMAND=(Get-Command pwsh).Source
 $env:DEVFLOW_AGENT_ARGS_JSON=@(("-NoProfile","-File",$agent,"{prompt_file}")|ConvertTo-Json -Compress)
 Push-Location $checkout
 try{
  $timer=[Diagnostics.Stopwatch]::StartNew()
  & pwsh -NoProfile -File (Join-Path $checkout "scripts/git-cli-multiflow-parallel.ps1") -StateRoot $state -MaxParallel 3 -MaxTasks 4 -TaskTimeoutSeconds 60
  if($LASTEXITCODE -ne 0){throw "Parallel engine exited with $LASTEXITCODE."}
  $timer.Stop()
 }finally{Pop-Location}
 $events=@(Get-Content $log|ForEach-Object{$p=$_.Split('|');[pscustomobject]@{kind=$p[0];ms=[long]$p[1];pid=$p[2]}})
 $starts=@($events|Where-Object kind -eq "start")
 $ends=@($events|Where-Object kind -eq "end")
 if($starts.Count -ne 3 -or $ends.Count -ne 3){throw "Expected three complete fake-agent runs; got starts=$($starts.Count), ends=$($ends.Count)."}
 $delta=[Math]::Abs($starts[0].ms-$starts[1].ms)
 if($delta -gt 2500){throw "Three workers did not overlap; start spread was $($delta)ms."}
 if($timer.Elapsed.TotalSeconds -gt 25){throw "Parallel run took too long ($($timer.Elapsed.TotalSeconds)s), expected overlapping workers; worker start-time overlap is asserted separately."}
 $stateData=Get-Content (Join-Path $state "state.json") -Raw|ConvertFrom-Json
 foreach($id in @("BUILD-99001","BUILD-99002","BUILD-99003")){
  if($stateData.tasks.$id.status -ne "draft_pr_created"){throw "Unexpected final state for ${id}: $($stateData.tasks.$id.status)"}
 }
 $remoteBranches=@(& git --git-dir=$origin branch --list "autopilot/*")
 if($remoteBranches.Count -ne 3){throw "Expected exactly three independent worker branches; dependency-gated task must not run."}
 Push-Location $checkout
 try{
  & pwsh -NoProfile -File (Join-Path $checkout "scripts/git-cli-multiflow-parallel.ps1") -StateRoot $state -MaxParallel 3 -MaxTasks 4 -TaskTimeoutSeconds 60
  if($LASTEXITCODE -ne 0){throw "Idempotent rerun exited with $LASTEXITCODE."}
 }finally{Pop-Location}
 $branchesAfterRerun=@(& git --git-dir=$origin branch --list "autopilot/*")
 if($branchesAfterRerun.Count -ne 3){throw "Completed Draft PR tasks were dispatched again on rerun."}
 if($events.Count -lt 3 -or ($events|Where-Object kind -eq "credential-leak").Count -gt 0){throw "Supervisor GitHub credentials leaked into an Agent process."}
 $workerRoots=@(Get-ChildItem -LiteralPath (Join-Path (Split-Path $checkout -Parent) "checkout-worktrees") -Directory -ErrorAction SilentlyContinue)
 $validated=@($workerRoots|Where-Object{Test-Path (Join-Path $_.FullName ".validator-ran")})
 if($validated.Count -ne 3){throw "Expected task-worktree validators to execute in all three isolated worktrees; got $($validated.Count)."}
 if($stateData.tasks."BUILD-99004"){throw "Dependency-gated task unexpectedly entered worker state."}
 if($stateData.tasks."BUILD-99005"){throw "Task with an open PR body reference was unexpectedly dispatched."}
 Write-Host "PASS: three fake agents overlapped (start spread $($delta)ms), produced Draft PR states, and pushed isolated branches."
}finally{
 $env:PATH=$originalPath
 if($null -eq $oldGhToken){Remove-Item Env:GH_TOKEN -ErrorAction SilentlyContinue}else{$env:GH_TOKEN=$oldGhToken}
 Remove-Item Env:DEVFLOW_TEST_LOG,Env:DEVFLOW_AGENT_COMMAND,Env:DEVFLOW_AGENT_ARGS_JSON -ErrorAction SilentlyContinue
 if($temp -and (Test-Path $temp)){Remove-Item -LiteralPath $temp -Recurse -Force}
}
