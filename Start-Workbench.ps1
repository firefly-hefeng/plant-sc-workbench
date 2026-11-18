param([int]$Port=8876, [ValidateRange(1,32)][int]$MaxJobs=2, [switch]$NoBrowser)
$ErrorActionPreference='Stop'
$projectRoot=$PSScriptRoot
$py=Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) {throw 'Run Setup.ps1 once to install the local scientific environment.'}
$url="http://127.0.0.1:$Port"
$ok=$false
try {$ok=(Invoke-RestMethod "$url/api/health" -TimeoutSec 2).product -eq 'plant-sc-workbench'} catch {}
if (-not $ok) {
    $logDir=Join-Path $projectRoot 'workspace'
    [IO.Directory]::CreateDirectory($logDir) | Out-Null
    $proc=Start-Process -FilePath $py -ArgumentList @('app.py','--port',"$Port",'--max-jobs',"$MaxJobs") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'service.out.log') -RedirectStandardError (Join-Path $logDir 'service.err.log') -PassThru
    for ($n=0; $n -lt 45; $n++) {
        Start-Sleep -Milliseconds 400
        try {$ok=(Invoke-RestMethod "$url/api/health" -TimeoutSec 1).product -eq 'plant-sc-workbench'} catch {}
        if ($ok) {break}
        if ($proc.HasExited) {break}
    }
    if (-not $ok) {throw "Service did not start. See $logDir\service.err.log"}
}
if (-not $NoBrowser) {Start-Process $url}
Write-Output $url

