[CmdletBinding()]
param([switch]$Plan,[switch]$Run,[string]$Task,[string]$Base,[string]$AgentCommand=$env:DEVFLOW_AGENT_COMMAND,[string]$AgentArgsJson=$env:DEVFLOW_AGENT_ARGS_JSON,[ValidateRange(1,20)][int]$MaxTasks=3)
$ErrorActionPreference="Stop"
if($PSVersionTable.PSVersion.Major -lt 7){throw "PowerShell 7 or newer is required. Start this script with pwsh."}
if($Run){
 $engine=Join-Path $PSScriptRoot "git-cli-multiflow-parallel.ps1"
 if(-not(Test-Path $engine)){throw "Parallel worker engine missing: $engine"}
 $repoRoot=(git rev-parse --show-toplevel 2>$null)
 if($LASTEXITCODE -ne 0 -or -not $repoRoot){throw "Run inside a Git checkout."}
 $repoRoot=$repoRoot.Trim()
 $manifest=Get-Content (Join-Path $repoRoot ".devflow/tasks.json") -Raw -Encoding UTF8|ConvertFrom-Json
 $stateRoot=Join-Path (Split-Path $repoRoot -Parent) ((Split-Path $repoRoot -Leaf)+"-multiflow-state")
 & $engine -StateRoot $stateRoot -MaxParallel ([Math]::Min(3,[int]$manifest.policy.max_parallel_worktrees))
 if($LASTEXITCODE -ne 0){throw "Parallel multiflow engine failed (exit $LASTEXITCODE)."}
 exit 0
}
function Invoke-GitCli($repo,[string[]]$GitArgs){ & git -C $repo @GitArgs; if($LASTEXITCODE -ne 0){throw "git failed (exit $LASTEXITCODE)"} }
function Root { $r=& git rev-parse --show-toplevel 2>$null; if($LASTEXITCODE -ne 0 -or -not $r){throw "Run inside a Git checkout."}; $r.Trim() }
function Eligible($manifest) {
 foreach($t in @($manifest.tasks|Where-Object{$_.status -in @("ready","in_progress")}|Sort-Object priority)){
  $ok=$true
  foreach($d in @($t.depends_on)){ $dep=@($manifest.tasks|Where-Object{$_.id -eq $d})|Select-Object -First 1; if(-not $dep -or $dep.status -ne "completed"){$ok=$false;break} }
  if($ok){$t}
 }
}
function Get-OpenTaskIds {
 & gh auth status *> $null
 if($LASTEXITCODE -ne 0){throw "GitHub CLI authentication required for duplicate-PR protection. Run gh auth login."}
 $json=& gh pr list --state open --json title --limit 100
 if($LASTEXITCODE -ne 0){throw "Could not inspect open PRs; refusing task execution."}
 @($json|ConvertFrom-Json|ForEach-Object{$match=[regex]::Match([string]$_.title,'BUILD-[0-9]{5}');if($match.Success){$match.Value}})
}
$root=Root;$manifestPath=Join-Path $root ".devflow\tasks.json"
if(-not(Test-Path $manifestPath)){throw "Missing .devflow/tasks.json"}
$m=Get-Content $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json
if(-not $Base){$Base=[string]$m.policy.default_base};if(-not $Base){throw "No base branch configured."}
$tasks=@(Eligible $m);if($Task){$tasks=@($tasks|Where-Object{$_.id -eq $Task})}
$ghReady=$false
if(Get-Command gh -ErrorAction SilentlyContinue){& gh auth status *> $null;$ghReady=($LASTEXITCODE -eq 0)}
if($Plan -or -not $Run){
 if($ghReady){$openIds=@(Get-OpenTaskIds);$tasks=@($tasks|Where-Object{$openIds -notcontains [string]$_.id})}
 else{Write-Warning "gh authentication unavailable; open-PR duplicate filtering cannot be verified. Run mode requires gh auth."}
 $tasks|Select-Object id,title,priority,status,depends_on|Format-Table -AutoSize
 if(-not $tasks.Count){Write-Host "No eligible tasks without an existing open PR. Dependency and external gates remain enforced."}
 exit 0
}
if(-not $AgentCommand){throw "Set DEVFLOW_AGENT_COMMAND to an installed coding-agent executable."}
if(-not $AgentArgsJson){throw 'Set DEVFLOW_AGENT_ARGS_JSON to a JSON array containing "{prompt_file}".'}
$agentArgs=ConvertFrom-Json -InputObject $AgentArgsJson
if($agentArgs -isnot [System.Array]){$agentArgs=@($agentArgs)}
if(@($agentArgs|Where-Object{$_ -eq "{prompt_file}"}).Count -eq 0){throw 'Agent args must include "{prompt_file}".'}
if(-not $ghReady){throw "GitHub CLI is required and must be authenticated. Run gh auth login first."}
if(& git -C $root status --porcelain){throw "Primary checkout must be clean."}
$openIds=@(Get-OpenTaskIds);$tasks=@($tasks|Where-Object{$openIds -notcontains [string]$_.id})
$count=0
foreach($t in $tasks){
 $wtCount=(@(& git -C $root worktree list --porcelain|Where-Object{$_ -like "worktree *"}).Count - 1)
 if($wtCount -ge [int]$m.policy.max_parallel_worktrees){Write-Warning "Worktree cap reached ($wtCount); remaining tasks deferred.";break}
 if($count -ge $MaxTasks){break}
 $id=[string]$t.id;$slug=$id.ToLowerInvariant();$stamp=Get-Date -Format "yyyyMMdd-HHmmss";$branch="autopilot/$slug-$stamp"
 $wtroot=Join-Path (Split-Path $root -Parent) ((Split-Path $root -Leaf)+"-worktrees");$wt=Join-Path $wtroot "$slug-$stamp"
 New-Item -ItemType Directory -Force -Path $wtroot|Out-Null
 Invoke-GitCli $root @("fetch","origin","--prune");Invoke-GitCli $root @("worktree","add","-b",$branch,$wt,"origin/$Base")
 $prompt=Join-Path $wt ".devflow-agent-task.md"
 $body=@("# $id - $($t.title)","Scope:",(@($t.scope)|ForEach-Object{"- $_"}),"Acceptance:",(@($t.acceptance)|ForEach-Object{"- $_"}),"Rules: inspect existing code, implement real behavior, run tests, document blockers; never merge, deploy, publish, change credentials, or mark dependencies complete.")
 Set-Content -LiteralPath $prompt -Value ($body -join [Environment]::NewLine) -Encoding utf8
 $expanded=foreach($a in $agentArgs){([string]$a).Replace("{prompt_file}",$prompt).Replace("{task_id}",$id).Replace("{worktree}",$wt)}
 $p=[System.Diagnostics.ProcessStartInfo]::new();$p.FileName=$AgentCommand;$p.WorkingDirectory=$wt;$p.UseShellExecute=$false;$p.RedirectStandardOutput=$true;$p.RedirectStandardError=$true
 foreach($a in $expanded){[void]$p.ArgumentList.Add($a)}
 $proc=[System.Diagnostics.Process]::new();$proc.StartInfo=$p
 if(-not $proc.Start()){throw "Agent failed to start; worktree retained: $wt"}
 $out=$proc.StandardOutput.ReadToEndAsync();$err=$proc.StandardError.ReadToEndAsync();$proc.WaitForExit()
 if($out.Result){Write-Host $out.Result};if($err.Result){Write-Host $err.Result}
 if($proc.ExitCode -ne 0){throw "Agent failed ($($proc.ExitCode)); worktree retained: $wt"}
 Remove-Item -LiteralPath $prompt -Force
 if(& git -C $wt status --porcelain -- .devflow/tasks.json){throw "Agent changed task manifest; worktree retained: $wt"}
 if(-not(& git -C $wt status --porcelain)){throw "Agent made no changes; worktree retained: $wt"}
 & python (Join-Path $wt "scripts/devflow.py") validate;if($LASTEXITCODE -ne 0){throw "Validation failed; worktree retained: $wt"}
 foreach($n in @(".env",".env.local","credentials.json","secrets.json")){if(Get-ChildItem $wt -Force -Recurse -File -Filter $n -ErrorAction SilentlyContinue|Where-Object{$_.FullName -notmatch '[\\/](\.git|node_modules|\.venv)[\\/]'} ){throw "Potential secret file blocks commit: $n"}}
 Invoke-GitCli $wt @("add","-A");Invoke-GitCli $wt @("diff","--cached","--check");Invoke-GitCli $wt @("commit","-m","BUILD: $id - $($t.title)");Invoke-GitCli $wt @("push","-u","origin",$branch)
 $prbody="Task: $id - $($t.title). Validation passed before commit. Draft only; no merge, deployment, publishing, or dependency status changes."
 & gh pr create --draft --base $Base --head $branch --title "BUILD: $id - $($t.title)" --body $prbody
 if($LASTEXITCODE -ne 0){throw "Push succeeded but PR creation failed; worktree retained: $wt"}
 $count++;Write-Host "[MULTIFLOW] Draft PR created for $id."
}
Write-Host "[MULTIFLOW] Completed $count task(s). Existing PR tasks are skipped; dependent tasks stay blocked until reviewed/merged and manually marked completed. No merge/deploy/publish."
