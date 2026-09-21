@echo off
setlocal

pushd "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
set "exitCode=%ERRORLEVEL%"
popd

if not "%exitCode%"=="0" (
    echo.
    echo Image Finisher exited with error code %exitCode%.
    pause
)

exit /b %exitCode%
