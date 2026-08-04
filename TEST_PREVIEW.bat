@echo off
setlocal
cd /d "%~dp0"
title WeChat Attendance Screenshot - Safe Preview

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0easy_setup.ps1" -Action Preview
set "ACTION_RESULT=%ERRORLEVEL%"

echo.
if not "%ACTION_RESULT%"=="0" (
    echo The preview did not complete. Read the message above for help.
)
echo Press any key to close this window.
pause >nul
exit /b %ACTION_RESULT%
