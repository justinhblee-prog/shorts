[CmdletBinding(DefaultParameterSetName = "Prepare")]
param(
 [Parameter(Mandatory=$true,ParameterSetName="Prepare")][string]$Task,
 [Parameter(ParameterSetName="Prepare")][string]$Base,
 [Parameter(Mandatory=$true,ParameterSetName="Finalize")][switch]$Finalize,
 [Parameter(Mandatory=$true,ParameterSetName="Status")][switch]$Status,
 [Parameter(ParameterSetName="Finalize")][string]$Title
)
$ErrorActionPreference="Stop"
function Invoke-Git { param([string[]]$GitArgs) & git @GitArgs; if($LASTEXITCODE -ne 0){throw "git $($GitArgs -join ' ') failed (exit $LASTEXITCODE)"} }
function Get-RepoRoot { $r=(& git rev-parse --show-toplevel 2>$null); if($LASTEXITCODE -ne 0 -or -not $r){throw "Not inside a Git repository."}; return $r.Trim() }
foreach($tool in @("git","gh")){if(-not(Get-Command $tool -ErrorAction SilentlyContinue)){throw "Required CLI not found: $tool"}}
& gh auth status *> $null
if($LASTEXITCODE -ne 0){throw "GitHub CLI authentication required. Run gh auth login once."}
$root=Get-RepoRoot
$manifestPath=Join-Path $root ".devflow\tasks.json"
if(-not(Test-Path $manifestPath)){throw "Task manifest not found: $manifestPath"}
$manifest=Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if($Status){
 Write-Host "=== Git status ==="; Invoke-Git -GitArgs @("-C",$root,"status","--short","--branch")
 Write-Host "=== Worktrees ==="; Invoke-Git -GitArgs @("-C",$root,"worktree","list"); exit 0
}
if($PSCmdlet.ParameterSetName -eq "Prepare"){
 $entry=@($manifest.tasks|Where-Object{$_.id -eq $Task})|Select-Object -First 1
 if(-not $entry){throw "Unknown task: $Task"}
 if($entry.status -notin @("ready","in_progress")){throw "Task is not runnable: $Task ($($entry.status))"}
 foreach($depId in @($entry.depends_on)){ $dep=@($manifest.tasks|Where-Object{$_.id -eq $depId})|Select-Object -First 1; if(-not $dep -or $dep.status -ne "completed"){throw "Dependency is not completed: $depId"} }
 if(-not $Base){$Base=$manifest.policy.default_base}; if(-not $Base){throw "No base branch configured."}
 $dirty=& git -C $root status --porcelain; if($LASTEXITCODE -ne 0){throw "Cannot inspect primary checkout."}; if($dirty){throw "Primary checkout is dirty. No files changed; commit or stash first."}
 Invoke-Git -GitArgs @("-C",$root,"fetch","origin","--prune")
 $baseRef="refs/remotes/origin/$Base"; & git -C $root show-ref --verify --quiet $baseRef
 if($LASTEXITCODE -ne 0){throw "Base branch not found on origin: $Base"}
 $slug=($Task.ToLowerInvariant() -replace "[^a-z0-9]+","-").Trim("-"); $stamp=Get-Date -Format "yyyyMMdd-HHmmss"
 $branchName="work/$slug-$stamp"; $wtRoot=Join-Path (Split-Path $root -Parent) ((Split-Path $root -Leaf)+"-worktrees"); $wt=Join-Path $wtRoot "$slug-$stamp"
 New-Item -ItemType Directory -Force -Path $wtRoot|Out-Null
 Invoke-Git -GitArgs @("-C",$root,"worktree","add","-b",$branchName,$wt,$baseRef)
 Write-Host "[GIT AUTOPILOT] Worktree prepared."; Write-Host "Task: $Task"; Write-Host "Branch: $branchName"; Write-Host "Base: $Base"; Write-Host "Worktree: $wt"
 Write-Host "After changes, run scripts/git-cli-autopilot.ps1 -Finalize from that worktree."; exit 0
}
if($Finalize){
 $wtRoot=Get-RepoRoot; $branchName=(& git branch --show-current).Trim()
 if($LASTEXITCODE -ne 0 -or -not $branchName -or $branchName -eq "HEAD"){throw "Finalize must run inside a task branch checkout."}
 $changes=& git status --porcelain; if($LASTEXITCODE -ne 0){throw "Cannot inspect working tree."}; if(-not $changes){throw "No changes to commit. Refusing empty PR."}
 $m=[regex]::Match($branchName,"work/(build-[0-9]+)-"); if(-not $m.Success){throw "Branch name does not contain a BUILD task ID: $branchName"}
 $taskId=$m.Groups[1].Value.ToUpperInvariant(); $entry=@($manifest.tasks|Where-Object{$_.id -eq $taskId})|Select-Object -First 1
 if(-not $entry){throw "Task not found in manifest: $taskId"}
 $validator=Join-Path $wtRoot "scripts\devflow.py"
 if(Test-Path $validator){& python $validator validate; if($LASTEXITCODE -ne 0){throw "Validation failed. Changes retained; no commit or PR created."}}
 else{Write-Warning "scripts/devflow.py missing. Git diff checks only; task validation is not complete."; Invoke-Git -GitArgs @("diff","--check")}
 Invoke-Git -GitArgs @("add","-A"); Invoke-Git -GitArgs @("diff","--cached","--check")
 $commitTitle="BUILD: $taskId - $($entry.title)"; Invoke-Git -GitArgs @("commit","-m",$commitTitle); Invoke-Git -GitArgs @("push","-u","origin",$branchName)
 $baseBranch=$manifest.policy.default_base; if(-not $baseBranch){throw "Manifest default_base missing; branch pushed but PR not created."}
 $prTitle=if($Title){$Title}else{$commitTitle}; $body="Task: $taskId - $($entry.title). Local validation passed if configured. External gates remain open. Draft only; no merge, deployment, or publishing."
 & gh pr create --draft --base $baseBranch --head $branchName --title $prTitle --body $body
 if($LASTEXITCODE -ne 0){throw "Push succeeded but Draft PR creation failed. No changes discarded."}
 Write-Host "[GIT AUTOPILOT] Draft PR created. No merge/deploy/publish performed."
}
