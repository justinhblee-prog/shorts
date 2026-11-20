[CmdletBinding()]
param(
 [ValidateRange(15,600)][int]$TimeoutSeconds=120
)
$ErrorActionPreference = "Stop"
if($PSVersionTable.PSVersion.Major -lt 7){throw "PowerShell 7+ is required."}
$command=[string]$env:DEVFLOW_AGENT_COMMAND
$argsJson=[string]$env:DEVFLOW_AGENT_ARGS_JSON
if(-not $command -or -not $argsJson){throw "DEVFLOW_AGENT_COMMAND and DEVFLOW_AGENT_ARGS_JSON must be available in this process."}
try{$agentArgs=ConvertFrom-Json -InputObject $argsJson}catch{throw "DEVFLOW_AGENT_ARGS_JSON is not valid JSON."}
if($agentArgs -isnot [array]){$agentArgs=@($agentArgs)}
$fileCount=@($agentArgs|Where-Object{$_ -eq "{prompt_file}"}).Count
$textCount=@($agentArgs|Where-Object{$_ -eq "{prompt_text}"}).Count
if(($fileCount+$textCount) -ne 1){throw 'Agent args must contain exactly one "{prompt_file}" or "{prompt_text}" placeholder.'}
. (Join-Path $PSScriptRoot "devflow-agent-process.ps1")
$root=(& git rev-parse --show-toplevel 2>$null)
if($LASTEXITCODE -ne 0 -or -not $root){throw "Run from a Git checkout."}
$root=$root.Trim()
$token="DEVFLOW_AGENT_SMOKE_OK"
$prompt="This is a one-request execution smoke test. Do not inspect or modify files, do not call tools, and do not perform project work. Reply with exactly this token and nothing else: $token"
$tempPrompt=Join-Path ([IO.Path]::GetTempPath()) ("devflow-agent-smoke-"+[guid]::NewGuid().ToString("N")+".txt")
try{
 [IO.File]::WriteAllText($tempPrompt,$prompt,[Text.UTF8Encoding]::new($false))
 $expanded=foreach($arg in $agentArgs){
  $value=([string]$arg).Replace("{prompt_file}",$tempPrompt)
  if($textCount -eq 1){$value=$value.Replace("{prompt_text}",$prompt)}
  $value
 }
 $psi=New-DevflowAgentProcessStartInfo -Command $command -Arguments @($expanded) -WorkingDirectory $root
 $process=[Diagnostics.Process]::new();$process.StartInfo=$psi
 if(-not $process.Start()){throw "Configured Agent CLI process did not start."}
 $stdout=$process.StandardOutput.ReadToEndAsync()
 $stderr=$process.StandardError.ReadToEndAsync()
 if(-not $process.WaitForExit($TimeoutSeconds*1000)){
  try{$process.Kill($true)}catch{}
  throw "Agent CLI smoke test timed out after $TimeoutSeconds seconds."
 }
 $out=[string]$stdout.Result
 $err=[string]$stderr.Result
 if($process.ExitCode -ne 0){throw "Agent CLI exited with code $($process.ExitCode). stderr: $err"}
 if($out -notmatch [regex]::Escape($token)){throw "Agent CLI completed but did not return the expected smoke-test token. stdout: $out; stderr: $err"}
 Write-Host "PASS: real configured Agent CLI started, returned the expected response, and exited successfully."
}finally{
 Remove-Item -LiteralPath $tempPrompt -Force -ErrorAction SilentlyContinue
}
