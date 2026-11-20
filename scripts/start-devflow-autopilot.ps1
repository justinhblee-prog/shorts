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
 $argsList=@()
 if($Plan){$argsList+="-Plan"}
 if($Run){$argsList+="-Run"}
 if($Task){$argsList+=@("-Task",$Task)}
 if($Base){$argsList+=@("-Base",$Base)}
 if($AgentCommand){$argsList+=@("-AgentCommand",$AgentCommand)}
 if($AgentArgsJson){$argsList+=@("-AgentArgsJson",$AgentArgsJson)}
 $argsList+=@("-MaxTasks",$MaxTasks)
 & $runner @argsList
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
