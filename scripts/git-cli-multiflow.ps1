[CmdletBinding()]
param([switch]$Plan,[switch]$Run,[string]$Task,[string]$Base,[string]$AgentCommand=$env:DEVFLOW_AGENT_COMMAND,[string]$AgentArgsJson=$env:DEVFLOW_AGENT_ARGS_JSON,[ValidateRange(1,20)][int]$MaxTasks=3
)
$ErrorActionPreference="Stop"
function Invoke-GitCli($repo,[string[]]$GitArgs){ & git -C $repo @GitArgs; if($LASTEXITCODE -ne 0){throw "git failed (exit $LASTEXITCODE)"} }
function Root { $r=& git rev-parse --show-toplevel 2>$null; if($LASTEXITCODE -ne 0 -or -not $r){throw "Run inside a Git checkout."}; $r.Trim() }
function Eligible($m,$allow) {
 $states=@("ready","in_progress")
 foreach($t in @($m.tasks|Where-Object{$_.status -in $states}|Sort-Object priority)){
  $ok=$true
  foreach($d in @($t.depends_on)){ $dep=@($m.tasks|Where-Object{$_.id -eq $d})|Select-Object -First 1; if(-not $dep -or $dep.status -ne "completed"){$ok=$false;break} }
  if($ok){$t}
 }
}
function RunAgent($exe,[string[]]$AgentArgs,$cwd){
 $p=[System.Diagnostics.ProcessStartInfo]::new(); $p.FileName=$exe; $p.WorkingDirectory=$cwd; $p.UseShellExecute=$false; $p.RedirectStandardOutput=$true; $p.RedirectStandardError=$true
 foreach($a in $AgentArgs){[void]$p.ArgumentList.Add($a)}
 $proc=[System.Diagnostics.Process]::new();$proc.StartInfo=$p
 if(-not $proc.Start()){throw "Agent failed to start."}
 $out=$proc.StandardOutput.ReadToEndAsync();$err=$proc.StandardError.ReadToEndAsync();$proc.WaitForExit()
 if($out.Result){Write-Host $out.Result};if($err.Result){Write-Host $err.Result};if($proc.ExitCode -ne 0){throw "Agent failed ($($proc.ExitCode)); worktree retained."}
}
$root=Root;$manifestPath=Join-Path $root ".devflow\tasks.json";if(-not(Test-Path $manifestPath)){throw "Missing .devflow/tasks.json"}
$m=Get-Content $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json
if(-not $Base){$Base=[string]$m.policy.default_base};if(-not $Base){throw "No base branch configured."}
$tasks=@(Eligible $m $true);if($Task){$tasks=@($tasks|Where-Object{$_.id -eq $Task})}
if($Plan -or -not $Run){$tasks|Select-Object id,title,priority,status,depends_on|Format-Table -AutoSize;if(-not $tasks.Count){Write-Host "No eligible tasks; dependency and external gates remain enforced."};exit 0}
if(-not $AgentCommand){throw "Set DEVFLOW_AGENT_COMMAND to an installed coding-agent executable."}
if(-not $AgentArgsJson){throw 'Set DEVFLOW_AGENT_ARGS_JSON to a JSON array containing "{prompt_file}".'}
$agentArgs=ConvertFrom-Json -AsArray $AgentArgsJson
if(@($agentArgs|Where-Object{$_ -eq "{prompt_file}"}).Count -eq 0){throw 'Agent args must include "{prompt_file}".'}
if(-not(Get-Command gh -ErrorAction SilentlyContinue)){throw "GitHub CLI is required."}
& gh auth status *> $null;if($LASTEXITCODE -ne 0){throw "Run gh auth login first."}
if(& git -C $root status --porcelain){throw "Primary checkout must be clean."}
$openPrsJson=& gh pr list --state open --json title --limit 100
if($LASTEXITCODE -ne 0){throw "Could not inspect open Draft PRs; refusing duplicate task execution."}
$openPrTitles=@($openPrsJson|ConvertFrom-Json|ForEach-Object{[string]$_.title})
$tasks=@($tasks|Where-Object{ $id=[string]$_.id; -not ($openPrTitles|Where-Object{$_ -match [regex]::Escape($id)}) })
$count=0
foreach($t in $tasks){
 $wtCount=(@(& git -C $root worktree list --porcelain|Where-Object{$_ -like "worktree *"}).Count - 1)
 if($wtCount -ge [int]$m.policy.max_parallel_worktrees){Write-Warning "Worktree cap reached ($wtCount); remaining tasks deferred.";break}
 if($count -ge $MaxTasks){break}
 $id=[string]$t.id;$slug=$id.ToLowerInvariant();$stamp=Get-Date -Format "yyyyMMdd-HHmmss";$branch="autopilot/$slug-$stamp"
 $wtroot=Join-Path (Split-Path $root -Parent) ((Split-Path $root -Leaf)+"-worktrees");$wt=Join-Path $wtroot "$slug-$stamp"
 New-Item -ItemType Directory -Force -Path $wtroot|Out-Null
 Invoke-GitCli $root @("fetch","origin","--prune");Git $root @("worktree","add","-b",$branch,$wt,"origin/$Base")
 $prompt=Join-Path $wt ".devflow-agent-task.md"
 $body=@("# $id - $($t.title)","Scope:",(@($t.scope)|ForEach-Object{"- $_"}),"Acceptance:",(@($t.acceptance)|ForEach-Object{"- $_"}),"Rules: inspect existing code, implement real behavior, run tests, document blockers; never merge, deploy, publish, change credentials, or mark dependencies complete.")
 Set-Content -LiteralPath $prompt -Value ($body -join [Environment]::NewLine) -Encoding utf8
 $expanded=foreach($a in $agentArgs){$a.Replace("{prompt_file}",$prompt).Replace("{task_id}",$id).Replace("{worktree}",$wt)}
 RunAgent $AgentCommand @($expanded) $wt
 Remove-Item -LiteralPath $prompt -Force
 if(-not(& git -C $wt status --porcelain)){throw "Agent made no changes; worktree retained: $wt"}
 & python (Join-Path $wt "scripts/devflow.py") validate;if($LASTEXITCODE -ne 0){throw "Validation failed; worktree retained: $wt"}
 foreach($n in @(".env",".env.local","credentials.json","secrets.json")){if(Get-ChildItem $wt -Force -Recurse -File -Filter $n -ErrorAction SilentlyContinue|Where-Object{$_.FullName -notmatch '[\\/](\.git|node_modules|\.venv)[\\/]'}){throw "Potential secret file blocks commit: $n"}}
 Invoke-GitCli $wt @("add","-A");Git $wt @("diff","--cached","--check");Git $wt @("commit","-m","BUILD: $id - $($t.title)");Git $wt @("push","-u","origin",$branch)
 $prbody="Task: $id - $($t.title). Validation passed before commit. Draft only; no merge, deployment, publishing, or dependency status changes."
 & gh pr create --draft --base $Base --head $branch --title "BUILD: $id - $($t.title)" --body $prbody
 if($LASTEXITCODE -ne 0){throw "Push succeeded but PR creation failed; worktree retained: $wt"}
 $count++;Write-Host "[MULTIFLOW] Draft PR created for $id."
}
Write-Host "[MULTIFLOW] Completed $count task(s). Tasks with existing open PRs are skipped; dependent tasks stay blocked until reviewed/merged and manually marked completed. No merge/deploy/publish."
