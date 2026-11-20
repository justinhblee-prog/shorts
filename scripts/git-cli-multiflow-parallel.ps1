[CmdletBinding()]
param(
 [switch]$Worker,[string]$TaskFile,[string]$StateRoot,[string]$Task,[string]$Base,
 [ValidateRange(1,3)][int]$MaxParallel=3,
 [ValidateRange(60,86400)][int]$TaskTimeoutSeconds=3600,
 [ValidateRange(1,20)][int]$MaxTasks=3
)
$ErrorActionPreference="Stop"
if($PSVersionTable.PSVersion.Major -lt 7){throw "PowerShell 7 or newer is required."}
function Read-State([string]$Path){
 if(-not(Test-Path $Path)){return @{schema_version=1;tasks=@{}}}
 return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable)
}
function Test-LeaseHeld([string]$Id,[string]$Root){
 $path=Join-Path (Join-Path $Root "leases") "$Id.lease"
 if(-not(Test-Path $path)){return $false}
 try{$probe=[IO.File]::Open($path,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);$probe.Dispose();return $false}catch{return $true}
}
function Set-State([string]$Path,[string]$Id,[string]$Status,[string]$Detail){
 $lockPath="$Path.lock";$lock=$null
 for($i=0;$i -lt 100 -and -not $lock;$i++){try{$lock=[IO.File]::Open($lockPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}catch{Start-Sleep -Milliseconds 100}}
 if(-not $lock){throw "State lock timeout: $Path"}
 try{
  $s=Read-State $Path
  if(-not ($s.tasks.Keys -contains $Id)){$s.tasks[$Id]=@{}}
  $s.tasks[$Id].status=$Status;$s.tasks[$Id].detail=$Detail;$s.tasks[$Id].updated_at=[DateTime]::UtcNow.ToString("o")
  $tmp="$Path.$([guid]::NewGuid().ToString('N')).tmp"
  [IO.File]::WriteAllText($tmp,($s|ConvertTo-Json -Depth 20),[Text.UTF8Encoding]::new($false))
  Move-Item -LiteralPath $tmp -Destination $Path -Force
 }finally{$lock.Dispose()}
}
if($Worker){
 $task=Get-Content -LiteralPath $TaskFile -Raw -Encoding UTF8|ConvertFrom-Json
 $id=[string]$task.id;$statePath=Join-Path $StateRoot "state.json"
 $leaseDir=Join-Path $StateRoot "leases";New-Item -ItemType Directory -Force -Path $leaseDir|Out-Null
 $leasePath=Join-Path $leaseDir "$id.lease"
 $lease=$null
 try{$lease=[IO.File]::Open($leasePath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}catch{throw "Fenced: another worker owns lease for $id"}
 try{
  $fence=[guid]::NewGuid().ToString("N")
  $lease.SetLength(0);$b=[Text.Encoding]::UTF8.GetBytes("$fence|$([DateTime]::UtcNow.ToString('o'))");$lease.Write($b,0,$b.Length);$lease.Flush($true)
  Set-State $statePath $id "running" "fence=$fence"
  $argsJson=$env:DEVFLOW_AGENT_ARGS_JSON;$command=$env:DEVFLOW_AGENT_COMMAND
  if(-not $command -or -not $argsJson){throw "Agent CLI configuration missing."}
  $agentArgs=ConvertFrom-Json -InputObject $argsJson;if($agentArgs -isnot [array]){$agentArgs=@($agentArgs)}
  if(@($agentArgs|Where-Object{$_ -eq "{prompt_file}"}).Count -eq 0){throw "Agent args must include {prompt_file}."}
  $expanded=foreach($a in $agentArgs){([string]$a).Replace("{prompt_file}",$task.prompt).Replace("{task_id}",$id).Replace("{worktree}",$task.worktree)}
  $psi=[Diagnostics.ProcessStartInfo]::new();$psi.FileName=$command;$psi.WorkingDirectory=$task.worktree;$psi.UseShellExecute=$false;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
  foreach($a in $expanded){[void]$psi.ArgumentList.Add($a)}
  $agent=[Diagnostics.Process]::new();$agent.StartInfo=$psi
  if(-not $agent.Start()){throw "Agent did not start."}
  $stdout=$agent.StandardOutput.ReadToEndAsync();$stderr=$agent.StandardError.ReadToEndAsync()
  if(-not $agent.WaitForExit([int]$task.timeout_seconds*1000)){try{$agent.Kill($true)}catch{};throw "Agent timeout."}
  if($stdout.Result){Write-Output $stdout.Result};if($stderr.Result){Write-Output $stderr.Result}
  if($agent.ExitCode -ne 0){throw "Agent exit code $($agent.ExitCode)."}
  Remove-Item -LiteralPath $task.prompt -Force -ErrorAction SilentlyContinue
  if(& git -C $task.worktree status --porcelain -- .devflow/tasks.json){throw "Protected task manifest was modified."}
  if(-not(& git -C $task.worktree status --porcelain)){throw "Agent produced no changes."}
  & python (Join-Path $task.worktree "scripts/devflow.py") validate;if($LASTEXITCODE -ne 0){throw "Validation failed."}
  foreach($n in @(".env",".env.local","credentials.json","secrets.json")){
   $secret=Get-ChildItem $task.worktree -Force -Recurse -File -Filter $n -ErrorAction SilentlyContinue|Where-Object{$_.FullName -notmatch '[\\/](\.git|node_modules|\.venv)[\\/]'}
   if($secret){throw "Potential secret file: $n"}
  }
  & git -C $task.worktree add -A;if($LASTEXITCODE -ne 0){throw "git add failed."}
  & git -C $task.worktree diff --cached --check;if($LASTEXITCODE -ne 0){throw "git diff check failed."}
  & git -C $task.worktree commit -m "BUILD: $id - $($task.title)";if($LASTEXITCODE -ne 0){throw "commit failed."}
  & git -C $task.worktree push -u origin $task.branch;if($LASTEXITCODE -ne 0){throw "push failed."}
  & gh pr create --draft --base $task.base --head $task.branch --title "BUILD: $id - $($task.title)" --body "Task $id validated by isolated worker. Draft only; no merge, deployment, publishing, or dependency completion."
  if($LASTEXITCODE -ne 0){throw "Draft PR creation failed after push."}
  Set-State $statePath $id "draft_pr_created" "fence=$fence; branch=$($task.branch)"
 }catch{
  Set-State $statePath $id "failed" $_.Exception.Message
  throw
 }finally{if($lease){$lease.Dispose()}}
 exit 0
}
if(-not $StateRoot){throw "StateRoot is required."}
$root=(& git rev-parse --show-toplevel 2>$null);if($LASTEXITCODE -ne 0){throw "Run inside a Git repository."};$root=$root.Trim()
if(& git -C $root status --porcelain){throw "Primary checkout must be clean."}
& gh auth status *> $null;if($LASTEXITCODE -ne 0){throw "GitHub CLI authentication required."}
if(-not $env:DEVFLOW_AGENT_COMMAND -or -not $env:DEVFLOW_AGENT_ARGS_JSON){throw "Configure DEVFLOW_AGENT_COMMAND and DEVFLOW_AGENT_ARGS_JSON."}
$manifest=Get-Content (Join-Path $root ".devflow/tasks.json") -Raw -Encoding UTF8|ConvertFrom-Json
$open=& gh pr list --state open --json title --limit 100;if($LASTEXITCODE -ne 0){throw "Cannot inspect open PRs; stopping safely."}
$openIds=@($open|ConvertFrom-Json|ForEach-Object{$m=[regex]::Match([string]$_.title,'BUILD-[0-9]{5}');if($m.Success){$m.Value}})
$eligible=@()
foreach($t in @($manifest.tasks|Where-Object{$_.status -in @("ready","in_progress")}|Sort-Object priority)){
 if($Task -and $t.id -ne $Task){continue}
 if($openIds -contains [string]$t.id){continue}
 $ready=$true
 foreach($d in @($t.depends_on)){$dep=@($manifest.tasks|Where-Object{$_.id -eq $d})|Select-Object -First 1;if(-not $dep -or $dep.status -ne "completed"){$ready=$false;break}}
 if($ready){$eligible+=$t}
}
if(-not $eligible.Count){Write-Host "No runnable tasks. Open-PR, dependency, and external gates remain enforced.";exit 0}
$stateDir=[IO.Path]::GetFullPath($StateRoot);New-Item -ItemType Directory -Force -Path $stateDir|Out-Null
$statePath=Join-Path $stateDir "state.json";$state=Read-State $statePath
$queue=[Collections.Generic.Queue[object]]::new()
foreach($t in @($eligible|Select-Object -First $MaxTasks)){
 $prior=$state.tasks[[string]$t.id]
 if($prior -and $prior.status -eq "draft_pr_created"){continue}
 if($prior -and $prior.status -eq "running"){
  if(Test-LeaseHeld ([string]$t.id) $stateDir){continue}
  Set-State $statePath ([string]$t.id) "failed" "Recovered stale running state; previous worker lease is no longer held."
 }
 if($prior -and $prior.status -eq "queued" -and (Test-LeaseHeld ([string]$t.id) $stateDir)){continue}
 $queue.Enqueue($t)
}
$active=[Collections.Generic.List[object]]::new()
while($queue.Count -gt 0 -or $active.Count -gt 0){
 while($queue.Count -gt 0 -and $active.Count -lt $MaxParallel){
  $t=$queue.Dequeue();$id=[string]$t.id;$stamp=Get-Date -Format "yyyyMMdd-HHmmssfff"
  $wtRoot=Join-Path (Split-Path $root -Parent) ((Split-Path $root -Leaf)+"-worktrees")
  $wt=Join-Path $wtRoot "$($id.ToLowerInvariant())-$stamp";$branch="autopilot/$($id.ToLowerInvariant())-$stamp"
  New-Item -ItemType Directory -Force -Path $wtRoot|Out-Null
  & git -C $root fetch origin --prune;if($LASTEXITCODE -ne 0){throw "git fetch failed."}
   $baseBranch=if($Base){$Base}else{[string]$manifest.policy.default_base}
  & git -C $root worktree add -b $branch $wt "origin/$baseBranch";if($LASTEXITCODE -ne 0){throw "worktree creation failed for $id."}
  $prompt=Join-Path $wt ".devflow-agent-task.md"
  $lines=@("# $id - $($t.title)","Scope:")+@($t.scope|ForEach-Object{"- $_"})+@("Acceptance:")+@($t.acceptance|ForEach-Object{"- $_"})+@("Do not edit task manifest, bypass gates, merge, deploy, publish, or change credentials.")
  Set-Content -LiteralPath $prompt -Value ($lines -join [Environment]::NewLine) -Encoding utf8
  $taskPath=Join-Path $stateDir "$id-$stamp.json"
  @{id=$id;title=$t.title;worktree=$wt;branch=$branch;base=$baseBranch;prompt=$prompt;timeout_seconds=$TaskTimeoutSeconds}|ConvertTo-Json|Set-Content -LiteralPath $taskPath -Encoding utf8
  Set-State $statePath $id "queued" "branch=$branch"
  $psi=[Diagnostics.ProcessStartInfo]::new();$psi.FileName=(Get-Command pwsh).Source;$psi.WorkingDirectory=$root;$psi.UseShellExecute=$false
  foreach($a in @("-NoProfile","-File",$PSCommandPath,"-Worker","-TaskFile",$taskPath,"-StateRoot",$stateDir)){[void]$psi.ArgumentList.Add($a)}
  $workerProcess=[Diagnostics.Process]::new();$workerProcess.StartInfo=$psi
  if(-not $workerProcess.Start()){throw "Could not start worker for $id."}
  $active.Add([pscustomobject]@{id=$id;process=$workerProcess;started=[DateTime]::UtcNow;worktree=$wt})
  Write-Host "[MULTIFLOW] Started $id on $branch"
 }
 Start-Sleep -Seconds 2
 for($i=$active.Count-1;$i -ge 0;$i--){
  $item=$active[$i];$item.process.Refresh()
  if($item.process.HasExited){
   if($item.process.ExitCode -ne 0){Write-Warning "$($item.id) failed; worktree retained at $($item.worktree)."}
   $active.RemoveAt($i)
  }elseif(([DateTime]::UtcNow-$item.started).TotalSeconds -gt $TaskTimeoutSeconds+90){
   try{$item.process.Kill($true)}catch{}
   Set-State $statePath $item.id "timed_out" "worker process tree terminated; worktree retained"
   $active.RemoveAt($i)
  }
 }
}
Write-Host "[MULTIFLOW] All workers exited. State: $statePath. Draft PRs only; no merge/deploy."
