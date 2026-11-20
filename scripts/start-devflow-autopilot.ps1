[CmdletBinding()]
param(
 [string]$Task,
 [switch]$Next,
 [switch]$Plan,
 [switch]$Run,
 [string]$Base,
 [string]$AgentCommand=$env:DEVFLOW_AGENT_COMMAND,
 [string]$AgentArgsJson=$env:DEVFLOW_AGENT_ARGS_JSON,
 [ValidateRange(1,20)][int]$MaxTasks=3
)
$ErrorActionPreference="Stop"
if($Plan -or $Run){
 $runner=Join-Path $PSScriptRoot "git-cli-multiflow.ps1"
 if(-not(Test-Path $runner)){throw "Git CLI multi-flow runner missing: $runner"}
 # Named splatting prevents JSON agent arguments from shifting into MaxTasks.
 # Plan is read-only and must not forward agent configuration at all.
 $runnerParams=@{ MaxTasks=$MaxTasks }
 if($Plan){$runnerParams.Plan=$true}
 if($Run){$runnerParams.Run=$true}
 if($Task){$runnerParams.Task=$Task}
 if($Base){$runnerParams.Base=$Base}
 if($Run -and $AgentCommand){$runnerParams.AgentCommand=$AgentCommand;$env:DEVFLOW_AGENT_COMMAND=$AgentCommand}
 if($Run -and $AgentArgsJson){$runnerParams.AgentArgsJson=$AgentArgsJson;$env:DEVFLOW_AGENT_ARGS_JSON=$AgentArgsJson}
 if($Run){
  $preflight=Join-Path $PSScriptRoot "git-cli-agent-config.ps1"
  if(-not(Test-Path $preflight)){throw "Agent CLI preflight missing: $preflight"}
  & $preflight -Check
 }
 & $runner @runnerParams
 if($LASTEXITCODE -ne 0){throw "Multi-flow runner failed (exit $LASTEXITCODE)."}
 exit 0
}
$scriptPath=Join-Path $PSScriptRoot "git-cli-autopilot.ps1"
if(-not(Test-Path $scriptPath)){throw "Git CLI orchestrator missing: $scriptPath"}
$argsList=@()
if($Next){$argsList+="-Next"}elseif($Task){$argsList+=@("-Task",$Task)}else{$argsList+="-Next"}
if($Base){$argsList+=@("-Base",$Base)}
& $scriptPath @argsList
if($LASTEXITCODE -ne 0){throw "Git CLI preparation failed (exit $LASTEXITCODE)."}
