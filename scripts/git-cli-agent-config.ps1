[CmdletBinding()]
param(
 [switch]$Configure,
 [switch]$Check,
 [switch]$ValidateOnly,
 [string]$AgentCommand,
 [string]$AgentArgsJson
)
$ErrorActionPreference="Stop"
function Test-AgentConfig([string]$Command,[string]$ArgsJson){
 if([string]::IsNullOrWhiteSpace($Command)){throw "Agent executable path/name is required."}
 if([string]::IsNullOrWhiteSpace($ArgsJson)){throw 'Agent args must be a JSON array containing "{prompt_file}".'}
 try{$parsed=ConvertFrom-Json -InputObject $ArgsJson -ErrorAction Stop}catch{throw "DEVFLOW_AGENT_ARGS_JSON is not valid JSON: $($_.Exception.Message)"}
 if($parsed -isnot [array]){throw "DEVFLOW_AGENT_ARGS_JSON must be a JSON array, not a string or object."}
 if(@($parsed|Where-Object{$_ -isnot [string]}).Count){throw "Every Agent argument must be a string."}
 if(@($parsed|Where-Object{$_ -eq "{prompt_file}"}).Count -ne 1){throw 'Agent args must contain "{prompt_file}" exactly once.'}
 $unsafe=@($parsed|Where-Object{$_ -match '(?i)(api[-_]?key|access[-_]?token|secret|password|authorization)\s*=' -or $_ -match '(?i)^--(api[-_]?key|token|secret|password|authorization)$'})
 if($unsafe.Count){throw "Do not put credentials in Agent arguments. Sign in with the Agent CLI's own login flow or use its documented credential store."}
}
if($ValidateOnly){
 Test-AgentConfig $AgentCommand $AgentArgsJson
 Write-Host "PASS: Agent configuration format is valid; prompt_file placeholder is present."
 exit 0
}
if($Configure){
 if(-not $AgentCommand){$AgentCommand=Read-Host "Installed Agent CLI executable (full path or command name)"}
 if(-not $AgentArgsJson){$AgentArgsJson=Read-Host 'Agent CLI argument JSON array; include "{prompt_file}" exactly once'}
 Test-AgentConfig $AgentCommand $AgentArgsJson
 $resolved=Get-Command $AgentCommand -ErrorAction SilentlyContinue
 if(-not $resolved -and -not(Test-Path -LiteralPath $AgentCommand)){throw "Agent executable not found. Install the CLI and authenticate it before configuring: $AgentCommand"}
 [Environment]::SetEnvironmentVariable("DEVFLOW_AGENT_COMMAND",$AgentCommand,"User")
 [Environment]::SetEnvironmentVariable("DEVFLOW_AGENT_ARGS_JSON",$AgentArgsJson,"User")
 $env:DEVFLOW_AGENT_COMMAND=$AgentCommand;$env:DEVFLOW_AGENT_ARGS_JSON=$AgentArgsJson
 Write-Host "Saved Agent CLI command and arguments to the current Windows user environment."
 Write-Host "Credentials were not read or stored. Authenticate using the Agent CLI's own login command."
}
if($Check -or $Configure){
 if($PSVersionTable.PSVersion.Major -lt 7){throw "PowerShell 7+ is required. Launch with pwsh."}
 foreach($tool in @("git","gh","python")){if(-not(Get-Command $tool -ErrorAction SilentlyContinue)){throw "Required executable missing from PATH: $tool"}}
 $root=& git rev-parse --show-toplevel 2>$null
 if($LASTEXITCODE -ne 0 -or -not $root){throw "Run from inside the shorts repository checkout."}
 $root=$root.Trim()
 if(-not(Test-Path (Join-Path $root ".devflow/tasks.json"))){throw "Task manifest missing from repository root."}
 if(& git -C $root status --porcelain){throw "Primary checkout is not clean. Commit or stash changes before running workers."}
 & gh auth status *> $null
 if($LASTEXITCODE -ne 0){throw "GitHub CLI is not authenticated. Run: gh auth login"}
 $command=if($AgentCommand){$AgentCommand}else{$env:DEVFLOW_AGENT_COMMAND}
 $args=if($AgentArgsJson){$AgentArgsJson}else{$env:DEVFLOW_AGENT_ARGS_JSON}
 Test-AgentConfig $command $args
 $resolved=Get-Command $command -ErrorAction SilentlyContinue
 if(-not $resolved -and -not(Test-Path -LiteralPath $command)){throw "Agent CLI executable is not installed or not on PATH: $command"}
 Write-Host "PASS: PowerShell $($PSVersionTable.PSVersion), Git, Python, GitHub CLI authentication, clean checkout, task manifest, and Agent CLI configuration."
 Write-Host "Agent executable resolved. Configuration values and credentials are not printed."
 Write-Host "Next: .\scripts\start-devflow-autopilot.ps1 -Plan"
 Write-Host "Run:  .\scripts\start-devflow-autopilot.ps1 -Run -MaxTasks 3"
}
