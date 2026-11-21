[CmdletBinding(SupportsShouldProcess=$true, ConfirmImpact="Medium")]
param(
 [string]$TaskName="NexusDevFlowSupervisor",
 [ValidateRange(1,20)][int]$MaxTasks=20,
 [ValidateRange(1,3600)][int]$PollIntervalSeconds=300,
 [switch]$StartNow,
 [switch]$Replace,
 [switch]$Uninstall,
 [switch]$ValidateOnly
)
$ErrorActionPreference="Stop"
if($PSVersionTable.PSVersion.Major -lt 7){throw "PowerShell 7+ is required. Run this installer with pwsh."}
if(-not $IsWindows){throw "This scheduled-task installer is supported on Windows only."}
if($ValidateOnly -and ($StartNow -or $Replace -or $Uninstall)){throw "ValidateOnly cannot be combined with StartNow, Replace or Uninstall."}
if($Uninstall -and ($StartNow -or $Replace -or $ValidateOnly)){throw "Uninstall cannot be combined with StartNow, Replace or ValidateOnly."}
$task=Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if($Uninstall){
 if(-not $task){Write-Host "Scheduled task '$TaskName' is not installed.";exit 0}
 if($PSCmdlet.ShouldProcess($TaskName,"Stop and unregister scheduled DevFlow supervisor")){
  if($task.State -eq "Running"){Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue}
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  Write-Host "Stopped and uninstalled scheduled task '$TaskName'."
 }else{Write-Host "No task changes made."}
 exit 0
}
$root=& git rev-parse --show-toplevel 2>$null
if($LASTEXITCODE -ne 0 -or -not $root){throw "Run inside the shorts Git checkout."}
$root=$root.Trim()
$launcher=Join-Path $root "scripts/start-devflow-detached.ps1"
if(-not(Test-Path -LiteralPath $launcher)){throw "Detached supervisor script is missing: $launcher"}
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$pwsh=(Get-Command pwsh -ErrorAction Stop).Source
$arguments=@(
 "-NoProfile","-NonInteractive","-File",$launcher,"-Supervisor",
 "-MaxTasks",[string]$MaxTasks,
 "-PollIntervalSeconds",[string]$PollIntervalSeconds
)
$argumentLine=($arguments|ForEach-Object{
 $value=[string]$_
 if($value -match '[\s"]'){' "'+$value.Replace('"','\"')+'"'}else{$value}
}) -join " "
$action=New-ScheduledTaskAction -Execute $pwsh -Argument $argumentLine -WorkingDirectory $root
$trigger=New-ScheduledTaskTrigger -AtLogOn -User $identity
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal=New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$definition=New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Starts the local NEXUS DevFlow detached scheduler at user logon. The scheduler polls the reviewed task manifest and creates Draft PRs only."
if($ValidateOnly){
 Write-Host "PASS: Task Scheduler action, logon trigger, current-user principal and non-overlapping restart settings are valid."
 Write-Host "Task=$TaskName; User=$identity; Repository=$root; MaxTasks=$MaxTasks; PollIntervalSeconds=$PollIntervalSeconds"
 exit 0
}
$preflight=Join-Path $root "scripts/git-cli-agent-config.ps1"
if(-not(Test-Path -LiteralPath $preflight)){throw "Agent CLI preflight script is missing: $preflight"}
& $preflight -Check
if($LASTEXITCODE -ne 0){throw "Agent CLI preflight failed; scheduled supervisor was not registered."}
if($task -and -not $Replace){throw "Scheduled task '$TaskName' already exists. Use -Replace to update it or -Uninstall to remove it."}
if($PSCmdlet.ShouldProcess($TaskName,"Register scheduled DevFlow supervisor at user logon")){
 if($task -and $Replace -and $task.State -eq "Running"){Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue}
 Register-ScheduledTask -TaskName $TaskName -InputObject $definition -Force | Out-Null
 if($StartNow){Start-ScheduledTask -TaskName $TaskName}
 Write-Host "Scheduled task '$TaskName' registered for user logon."
 Write-Host "Repository: $root"
 Write-Host "Polling interval: $PollIntervalSeconds seconds; max tasks per cycle: $MaxTasks."
 if($StartNow){Write-Host "Immediate start requested; inspect the sibling *-multiflow-logs status JSON and logs."}
 else{Write-Host "The task starts at the next Windows user logon. Use -StartNow to start it immediately."}
 Write-Host "The task runs as the current user with an interactive logon token; no password or credential is stored."
}else{Write-Host "No task changes made."}
