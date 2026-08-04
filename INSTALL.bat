@echo off
setlocal
cd /d "%~dp0"
title WeChat Attendance Screenshot - Install

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0easy_setup.ps1" -Action Install
set "ACTION_RESULT=%ERRORLEVEL%"

echo.
if not "%ACTION_RESULT%"=="0" (
    echo Installation did not complete. Read the message above for help.
)
echo Press any key to close this window.
pause >nul
exit /b %ACTION_RESULT%
