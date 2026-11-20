[CmdletBinding()]
param(
 [string]$Task = "BUILD-00352",
 [string]$Base
)
$ErrorActionPreference = "Stop"
$scriptPath=Join-Path $PSScriptRoot "git-cli-autopilot.ps1"
if(-not(Test-Path $scriptPath)){throw "Git CLI orchestrator missing: $scriptPath"}
$argsList=@("-Task",$Task)
if($Base){$argsList+=@("-Base",$Base)}
& $scriptPath @argsList
if($LASTEXITCODE -ne 0){throw "Git CLI preparation failed (exit $LASTEXITCODE)."}
