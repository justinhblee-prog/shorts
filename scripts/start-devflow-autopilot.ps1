[CmdletBinding()]
param(
 [string]$Task,
 [switch]$Next,
 [string]$Base
)
$ErrorActionPreference = "Stop"
$scriptPath=Join-Path $PSScriptRoot "git-cli-autopilot.ps1"
if(-not(Test-Path $scriptPath)){throw "Git CLI orchestrator missing: $scriptPath"}
$argsList=@()
if($Next){$argsList+= "-Next"} elseif($Task){$argsList+=@("-Task",$Task)} else {$argsList+= "-Next"}
if($Base){$argsList+=@("-Base",$Base)}
& $scriptPath @argsList
if($LASTEXITCODE -ne 0){throw "Git CLI preparation failed (exit $LASTEXITCODE)."}
