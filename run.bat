@echo off
cd /d "%~dp0"
title Hinata X Helper
call "%~dp0_findpy.bat" || (pause & exit /b 1)
"%PYEXE%" %PYARGS% -u main.py
if errorlevel 1 pause
