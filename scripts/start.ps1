$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repositoryRoot

$python = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
$frontend = Join-Path $repositoryRoot 'frontend\dist\index.html'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw '.venv was not found. Run the initial setup described in README.md.'
}
if (-not (Test-Path -LiteralPath $frontend -PathType Leaf)) {
    throw 'frontend/dist was not found. Run .\scripts\build.ps1 first.'
}

& $python -m backend.run
exit $LASTEXITCODE
