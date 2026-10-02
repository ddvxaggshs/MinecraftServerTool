@echo off
setlocal
cd /d "%~dp0"
title Minecraft Relay - Windows Builder
py --version >nul 2>nul
if errorlevel 1 (
  echo Python with the py launcher is required to build this project.
  pause
  exit /b 1
)
py -m pip install PySide6 pyinstaller
if errorlevel 1 goto :fail
py tools\build_release.py
if errorlevel 1 goto :fail
echo Build complete. Packages and update.json are in dist\VERSION.
pause
exit /b 0
:fail
echo Build failed. See the error above.
pause
exit /b 1
