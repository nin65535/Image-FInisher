$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repositoryRoot
& "$repositoryRoot\.venv\Scripts\python.exe" -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location "$repositoryRoot\frontend"
& npm test
exit $LASTEXITCODE
