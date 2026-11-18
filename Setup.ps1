$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) {throw 'Python 3.11 is required.'}
}
& '.venv/Scripts/python.exe' -m pip install -r requirements.txt -c requirements-lock.txt
if ($LASTEXITCODE -ne 0) {throw 'Python environment install failed.'}
& '.venv/Scripts/python.exe' -m pip check
if ($LASTEXITCODE -ne 0) {throw 'Dependency check failed.'}

