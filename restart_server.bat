@echo off
REM Simple script to restart the Anki viewer server
echo Stopping any running Python processes...
taskkill //F //IM python.exe 2>nul
if %errorlevel% equ 0 (
    echo Python processes stopped.
) else (
    echo No Python processes were running.
)

timeout /t 1 /nobreak >nul

echo Starting server...
start /B python app.py
echo Server started! Access it at http://localhost:5000
echo Press Ctrl+C to stop this script (server will continue running in background)
