@echo off
setlocal
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 goto :fail
py tools\build_release.py
if errorlevel 1 goto :fail
echo Built dist\MinecraftManager and dist\updater.exe.
pause
exit /b 0
:fail
echo Build failed. See the error above.
pause
exit /b 1
