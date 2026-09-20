$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location "$repositoryRoot\frontend"
& npm run build
exit $LASTEXITCODE
