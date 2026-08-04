@echo off
setlocal
cd /d "%~dp0"
title WeChat Attendance Screenshot - Disable Automatic Sending

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0easy_setup.ps1" -Action Disable
set "ACTION_RESULT=%ERRORLEVEL%"

echo.
if not "%ACTION_RESULT%"=="0" (
    echo Automatic sending could not be disabled. Read the message above for help.
)
echo Press any key to close this window.
pause >nul
exit /b %ACTION_RESULT%
