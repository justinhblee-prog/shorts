[CmdletBinding()]
param()
$ErrorActionPreference="Stop"
$originalPath=$env:PATH
if($PSVersionTable.PSVersion.Major -lt 7){throw "PowerShell 7+ required."}
$repoRoot=(git rev-parse --show-toplevel 2>$null)
if($LASTEXITCODE -ne 0 -or -not $repoRoot){throw "Run from the repository checkout."}
$engineSource=Join-Path $repoRoot "scripts/git-cli-multiflow-parallel.ps1"
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
 Set-Content (Join-Path $seed "scripts/devflow.py") "raise SystemExit(0)" -Encoding utf8
 $manifest=@{
  policy=@{default_base="main";max_parallel_worktrees=2;auto_merge=$false;auto_deploy=$false}
  tasks=@(
   @{id="BUILD-99001";title="parallel fixture A";status="ready";priority=1;depends_on=@();scope=@("write an isolated marker");acceptance=@("marker exists")},
   @{id="BUILD-99002";title="parallel fixture B";status="ready";priority=2;depends_on=@();scope=@("write an isolated marker");acceptance=@("marker exists")},
   @{id="BUILD-99003";title="dependent fixture C";status="ready";priority=3;depends_on=@("BUILD-99001");scope=@("must remain gated");acceptance=@("must not run before dependency completion")}
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
  'if "%1 %2"=="pr list" (echo [] & exit /b 0)',
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
  & pwsh -NoProfile -File (Join-Path $checkout "scripts/git-cli-multiflow-parallel.ps1") -StateRoot $state -MaxParallel 2 -MaxTasks 2 -TaskTimeoutSeconds 60
  if($LASTEXITCODE -ne 0){throw "Parallel engine exited with $LASTEXITCODE."}
  $timer.Stop()
 }finally{Pop-Location}
 $events=@(Get-Content $log|ForEach-Object{$p=$_.Split('|');[pscustomobject]@{kind=$p[0];ms=[long]$p[1];pid=$p[2]}})
 $starts=@($events|Where-Object kind -eq "start")
 $ends=@($events|Where-Object kind -eq "end")
 if($starts.Count -ne 2 -or $ends.Count -ne 2){throw "Expected two complete fake-agent runs; got starts=$($starts.Count), ends=$($ends.Count)."}
 $delta=[Math]::Abs($starts[0].ms-$starts[1].ms)
 if($delta -gt 2500){throw "Workers did not overlap; start delta was $($delta)ms."}
 if($timer.Elapsed.TotalSeconds -gt 12){throw "Parallel run took too long ($($timer.Elapsed.TotalSeconds)s), expected overlapping workers."}
 $stateData=Get-Content (Join-Path $state "state.json") -Raw|ConvertFrom-Json
 foreach($id in @("BUILD-99001","BUILD-99002")){
  if($stateData.tasks.$id.status -ne "draft_pr_created"){throw "Unexpected final state for ${id}: $($stateData.tasks.$id.status)"}
 }
 $remoteBranches=@(& git --git-dir=$origin branch --list "autopilot/*")
 if($remoteBranches.Count -ne 2){throw "Expected exactly two independent worker branches; dependency-gated task must not run."}
 & pwsh -NoProfile -File (Join-Path $checkout "scripts/git-cli-multiflow-parallel.ps1") -StateRoot $state -MaxParallel 2 -MaxTasks 3 -TaskTimeoutSeconds 60
 if($LASTEXITCODE -ne 0){throw "Idempotent rerun exited with $LASTEXITCODE."}
 $branchesAfterRerun=@(& git --git-dir=$origin branch --list "autopilot/*")
 if($branchesAfterRerun.Count -ne 2){throw "Completed Draft PR tasks were dispatched again on rerun."}
 if($stateData.tasks."BUILD-99003"){throw "Dependency-gated task unexpectedly entered worker state."}
 Write-Host "PASS: two fake agents overlapped (start delta $($delta)ms), produced Draft PR states, and pushed isolated branches."
}finally{
 $env:PATH=$originalPath
 Remove-Item Env:DEVFLOW_TEST_LOG,Env:DEVFLOW_AGENT_COMMAND,Env:DEVFLOW_AGENT_ARGS_JSON -ErrorAction SilentlyContinue
 if($temp -and (Test-Path $temp)){Remove-Item -LiteralPath $temp -Recurse -Force}
}
