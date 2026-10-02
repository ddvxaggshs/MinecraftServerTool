@echo off
setlocal
cd /d "%~dp0"
title Minecraft Relay - Build and Publish
py --version >nul 2>nul
if errorlevel 1 goto :fail
py -m pip install -r requirements.txt
if errorlevel 1 goto :fail
py tools\publish.py
if errorlevel 1 goto :fail
echo Published successfully. Friends can now check for updates.
pause
exit /b 0
:fail
echo Publish failed. See the error above. No force-push is performed.
pause
exit /b 1
