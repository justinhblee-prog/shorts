[CmdletBinding()]
param(
 [switch]$Supervisor,
 [string]$RunId,
 [string]$Task,
 [string]$Base,
 [ValidateRange(1,20)][int]$MaxTasks=20
)
$ErrorActionPreference="Stop"
if($PSVersionTable.PSVersion.Major -lt 7){throw "PowerShell 7 or newer is required. Start this script with pwsh."}
function Get-RepoRoot {
 $r=& git rev-parse --show-toplevel 2>$null
 if($LASTEXITCODE -ne 0 -or -not $r){throw "Run inside the shorts Git checkout."}
 return $r.Trim()
}
function Write-JsonAtomic([string]$Path,[object]$Value){
 $tmp="$Path.$([guid]::NewGuid().ToString('N')).tmp"
 [IO.File]::WriteAllText($tmp,($Value|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
 Move-Item -LiteralPath $tmp -Destination $Path -Force
}
function Quote-WindowsArgument([string]$Value){
 if($Value.Length -gt 0 -and $Value -notmatch '[\s"]'){return $Value}
 $sb=[Text.StringBuilder]::new();[void]$sb.Append('"');$slashes=0
 foreach($ch in $Value.ToCharArray()){
  if($ch -eq '\'){$slashes++;continue}
  if($ch -eq '"'){
   [void]$sb.Append(('\' * (2*$slashes+1)));[void]$sb.Append('"');$slashes=0;continue
  }
  if($slashes){[void]$sb.Append(('\' * $slashes));$slashes=0}
  [void]$sb.Append($ch)
 }
 if($slashes){[void]$sb.Append(('\' * (2*$slashes)))}
 [void]$sb.Append('"')
 return $sb.ToString()
}
$root=Get-RepoRoot
$repoName=Split-Path $root -Leaf
$stateRoot=Join-Path (Split-Path $root -Parent) ($repoName+"-multiflow-state")
$logRoot=Join-Path (Split-Path $root -Parent) ($repoName+"-multiflow-logs")
New-Item -ItemType Directory -Force -Path $stateRoot,$logRoot|Out-Null
$launcher=Join-Path $PSScriptRoot "start-devflow-autopilot.ps1"
if(-not(Test-Path -LiteralPath $launcher)){throw "Multi-flow launcher missing: $launcher"}
if($Supervisor){
 if(-not $RunId){throw "Supervisor RunId is required."}
 $lockPath=Join-Path $stateRoot "scheduler.lock"
 $lock=$null
 $statusPath=Join-Path $logRoot "$RunId.status.json"
 $exitCode=1
 try{
  try{$lock=[IO.File]::Open($lockPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
  catch{throw "Another multi-flow supervisor already owns the scheduler lease. Check the active run logs before starting another."}
  $psi=[Diagnostics.ProcessStartInfo]::new()
  $psi.FileName=(Get-Command pwsh -ErrorAction Stop).Source
  $psi.WorkingDirectory=$root
  $psi.UseShellExecute=$false
  foreach($arg in @("-NoProfile","-NoLogo","-NonInteractive","-File",$launcher,"-Run","-MaxTasks",[string]$MaxTasks)){[void]$psi.ArgumentList.Add($arg)}
  if($Task){[void]$psi.ArgumentList.Add("-Task");[void]$psi.ArgumentList.Add($Task)}
  if($Base){[void]$psi.ArgumentList.Add("-Base");[void]$psi.ArgumentList.Add($Base)}
  $runner=[Diagnostics.Process]::new();$runner.StartInfo=$psi
  if(-not $runner.Start()){throw "Could not start the multi-flow launcher process."}
  $runner.WaitForExit()
  $exitCode=$runner.ExitCode
  if($exitCode -ne 0){throw "Multi-flow launcher failed with exit code $exitCode."}
  Write-JsonAtomic $statusPath @{run_id=$RunId;status="completed";exit_code=0;finished_at=[DateTime]::UtcNow.ToString("o")}
 }catch{
  Write-Error $_
  Write-JsonAtomic $statusPath @{run_id=$RunId;status="failed";exit_code=1;error=$_.Exception.Message;finished_at=[DateTime]::UtcNow.ToString("o")}
  exit 1
 }finally{if($lock){$lock.Dispose()}}
 exit $exitCode
}
if(-not $env:DEVFLOW_AGENT_COMMAND -or -not $env:DEVFLOW_AGENT_ARGS_JSON){
 throw "Agent CLI configuration is missing. Run scripts/git-cli-agent-config.ps1 -Check before detaching."
}
$pwsh=(Get-Command pwsh -ErrorAction Stop).Source
$runId=Get-Date -Format "yyyyMMdd-HHmmss"
$runId+="-"+[guid]::NewGuid().ToString("N").Substring(0,8)
$stdout=Join-Path $logRoot "$runId.stdout.log"
$stderr=Join-Path $logRoot "$runId.stderr.log"
$runFile=Join-Path $logRoot "$runId.run.json"
$statusFile=Join-Path $logRoot "$runId.status.json"
$argsList=@("-NoProfile","-NoLogo","-NonInteractive","-File",$PSCommandPath,"-Supervisor","-RunId",$runId,"-MaxTasks",[string]$MaxTasks)
if($Task){$argsList+=@("-Task",$Task)}
if($Base){$argsList+=@("-Base",$Base)}
$quoted=($argsList|ForEach-Object{Quote-WindowsArgument ([string]$_)}) -join " "
$startedAt=[DateTime]::UtcNow.ToString("o")
Write-JsonAtomic $statusFile @{run_id=$runId;status="starting";started_at=$startedAt}
try{
 $process=Start-Process -FilePath $pwsh -ArgumentList $quoted -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
 Write-JsonAtomic $runFile @{
  run_id=$runId;pid=$process.Id;repository=$root;started_at=$startedAt
  stdout_log=$stdout;stderr_log=$stderr;status_file=$statusFile;max_tasks=$MaxTasks;task=$Task;base=$Base
 }
}catch{
 Write-JsonAtomic $statusFile @{run_id=$runId;status="failed_to_start";error=$_.Exception.Message;finished_at=[DateTime]::UtcNow.ToString("o")}
 throw
}
Write-Host "Detached multi-flow supervisor started. PID=$($process.Id)"
Write-Host "Run metadata: $runFile"
Write-Host "Logs: $stdout ; $stderr"
Write-Host "Status: $statusFile"
Write-Host "The supervisor is independent of this PowerShell window. It keeps the scheduler lease until completion."
