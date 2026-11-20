[CmdletBinding()]
param()
$ErrorActionPreference="Stop"
if($PSVersionTable.PSVersion.Major -lt 7){throw "PowerShell 7+ required."}
$root=(git rev-parse --show-toplevel 2>$null)
if($LASTEXITCODE -ne 0 -or -not $root){throw "Run from the repository checkout."}
$root=$root.Trim()
$temp=Join-Path ([IO.Path]::GetTempPath()) ("devflow-detached-test-"+[guid]::NewGuid().ToString("N"))
$repo=Join-Path $temp "shorts-fixture";$bin=Join-Path $temp "bin"
$originalPath=$env:PATH
$originalCommand=$env:DEVFLOW_AGENT_COMMAND
$originalArgs=$env:DEVFLOW_AGENT_ARGS_JSON
$supervisorPid=$null
try{
 New-Item -ItemType Directory -Force -Path $repo,$bin|Out-Null
 & git -C $repo init|Out-Null
 & git -C $repo config user.name "Detached Supervisor Test"
 & git -C $repo config user.email "detached-test@example.invalid"
 New-Item -ItemType Directory -Force -Path (Join-Path $repo "scripts"),(Join-Path $repo ".devflow")|Out-Null
 foreach($name in @("start-devflow-autopilot.ps1","start-devflow-detached.ps1","git-cli-multiflow.ps1","git-cli-multiflow-parallel.ps1","git-cli-agent-config.ps1")){
  Copy-Item (Join-Path $root "scripts/$name") (Join-Path $repo "scripts/$name")
 }
 $manifest=@{
  schema_version=1
  policy=@{max_parallel_worktrees=1;default_base="main";auto_merge=$false;auto_deploy=$false}
  tasks=@(@{id="BUILD-99009";title="blocked fixture";priority=1;status="blocked_external";depends_on=@();scope=@();acceptance=@()})
 }
 $manifest|ConvertTo-Json -Depth 20|Set-Content (Join-Path $repo ".devflow/tasks.json") -Encoding utf8
 & git -C $repo add -A
 & git -C $repo commit -m "detached supervisor fixture"|Out-Null
 & git -C $repo branch -M main
 $fakeGh=@(
  "@echo off",
  'if "%1 %2"=="auth status" exit /b 0',
  'if "%1 %2"=="pr list" (echo [] & exit /b 0)',
  "exit /b 0"
 ) -join [Environment]::NewLine
 Set-Content (Join-Path $bin "gh.cmd") $fakeGh -Encoding ascii
 $env:PATH="$bin;$env:PATH"
 $env:DEVFLOW_AGENT_COMMAND=(Get-Command pwsh -ErrorAction Stop).Source
 $env:DEVFLOW_AGENT_ARGS_JSON='["-NoProfile","-File","unused-agent.ps1","{prompt_file}"]'
 Push-Location $repo
 try{
  $output=& pwsh -NoProfile -File (Join-Path $repo "scripts/start-devflow-detached.ps1") -MaxTasks 1 2>&1
  if($LASTEXITCODE -ne 0){throw "Detached launcher failed: $($output -join [Environment]::NewLine)"}
 }finally{Pop-Location}
 $logRoot=Join-Path (Split-Path $repo -Parent) "shorts-fixture-multiflow-logs"
 $runFile=@(Get-ChildItem $logRoot -Filter "*.run.json"|Sort-Object LastWriteTime -Descending|Select-Object -First 1)
 if(-not $runFile){throw "Detached launcher did not write run metadata."}
 $run=Get-Content $runFile.FullName -Raw|ConvertFrom-Json
 $supervisorPid=[int]$run.pid
 $statusPath=[string]$run.status_file
 $deadline=[DateTime]::UtcNow.AddSeconds(45)
 $status=$null
 do{
  Start-Sleep -Milliseconds 250
  if(Test-Path $statusPath){$status=Get-Content $statusPath -Raw|ConvertFrom-Json}
 }while([DateTime]::UtcNow -lt $deadline -and $status.status -notin @("completed","failed","failed_to_start"))
 if(-not $status -or $status.status -ne "completed" -or $status.exit_code -ne 0){
  $stderr=if(Test-Path $run.stderr_log){Get-Content $run.stderr_log -Raw}else{"<no stderr log>"}
  throw "Detached supervisor did not complete successfully. Status=$($status.status); stderr=$stderr"
 }
 $stdout=Get-Content $run.stdout_log -Raw
 if($stdout -notmatch "No runnable tasks"){throw "Detached supervisor did not execute the multi-flow launcher. Output: $stdout"}
 $probe=$null
 try{$probe=[IO.File]::Open((Join-Path (Split-Path $repo -Parent) "shorts-fixture-multiflow-state/scheduler.lock"),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
 catch{throw "Scheduler lease remained held after supervisor completion."}
 finally{if($probe){$probe.Dispose()}}
 Write-Host "PASS: detached supervisor survived parent launcher return, executed the scheduler, persisted logs/status, and released its exclusive lease."
}finally{
 if($supervisorPid){
  $p=Get-Process -Id $supervisorPid -ErrorAction SilentlyContinue
  if($p){try{$p.Kill()}catch{}}
 }
 $env:PATH=$originalPath
 if($null -eq $originalCommand){Remove-Item Env:DEVFLOW_AGENT_COMMAND -ErrorAction SilentlyContinue}else{$env:DEVFLOW_AGENT_COMMAND=$originalCommand}
 if($null -eq $originalArgs){Remove-Item Env:DEVFLOW_AGENT_ARGS_JSON -ErrorAction SilentlyContinue}else{$env:DEVFLOW_AGENT_ARGS_JSON=$originalArgs}
 if(Test-Path $temp){Remove-Item -LiteralPath $temp -Recurse -Force}
}
