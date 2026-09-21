$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repositoryRoot

$python = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
$frontend = Join-Path $repositoryRoot 'frontend\dist\index.html'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw '.venv がありません。READMEの初回セットアップを実行してください。'
}
if (-not (Test-Path -LiteralPath $frontend -PathType Leaf)) {
    throw 'frontend/dist がありません。先に .\scripts\build.ps1 を実行してください。'
}

& $python -m backend.run
exit $LASTEXITCODE
