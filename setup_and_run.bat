@echo off
cd /d "%~dp0"
title Hinata X Helper - setup
call "%~dp0_findpy.bat" > install.log 2>&1 || (type install.log & pause & exit /b 1)
echo Python: %PYEXE% %PYARGS% >> install.log
"%PYEXE%" %PYARGS% --version >> install.log 2>&1
echo [1/2] Installing dependencies - first time takes a few minutes...
"%PYEXE%" %PYARGS% -m pip install --disable-pip-version-check -r requirements.txt >> install.log 2>&1
echo pip exit code %errorlevel% >> install.log
echo [2/2] Starting Hinata X Helper...
title Hinata X Helper
"%PYEXE%" %PYARGS% -u main.py
echo Hinata stopped with code %errorlevel%. >> hinata.log
pause
