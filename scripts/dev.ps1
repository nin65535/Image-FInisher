$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Start-Process -FilePath "$repositoryRoot\.venv\Scripts\python.exe" -ArgumentList '-m', 'uvicorn', 'backend.app.main:app', '--reload', '--host', '127.0.0.1', '--port', '8000' -WorkingDirectory $repositoryRoot -WindowStyle Hidden
Set-Location "$repositoryRoot\frontend"
& npm run dev
exit $LASTEXITCODE
