function New-DevflowAgentProcessStartInfo {
 [CmdletBinding()]
 param([Parameter(Mandatory)][string]$Command,[string[]]$Arguments=@(),[Parameter(Mandatory)][string]$WorkingDirectory)
 $resolved=Get-Command -Name $Command -ErrorAction Stop
 if($resolved.CommandType -notin @("Application","ExternalScript")){throw "Agent command must resolve to an executable or PowerShell script, not $($resolved.CommandType): $Command"}
 $path=if($resolved.Source){[string]$resolved.Source}elseif($resolved.Path){[string]$resolved.Path}else{[string]$resolved.Definition}
 if(-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)){throw "Resolved Agent CLI file does not exist: $Command"}
 $psi=[Diagnostics.ProcessStartInfo]::new()
 $psi.WorkingDirectory=$WorkingDirectory
 $psi.UseShellExecute=$false
 $psi.RedirectStandardOutput=$true
 $psi.RedirectStandardError=$true
 if([IO.Path]::GetExtension($path) -ieq ".ps1"){
  $pwsh=(Get-Command pwsh -ErrorAction Stop).Source
  $psi.FileName=$pwsh
  foreach($arg in @("-NoProfile","-File",$path)+$Arguments){[void]$psi.ArgumentList.Add([string]$arg)}
 }else{
  $psi.FileName=$path
  foreach($arg in $Arguments){[void]$psi.ArgumentList.Add([string]$arg)}
 }
 return $psi
}
