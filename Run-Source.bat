@echo off
rem Double-click Run-Source.vbs directly to avoid the initial batch console flash.
start "" "%SystemRoot%\System32\wscript.exe" "%~dp0Run-Source.vbs"
exit /b
