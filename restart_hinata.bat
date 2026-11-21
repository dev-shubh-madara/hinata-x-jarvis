@echo off
rem Restarts Hinata X Helper (stops every running copy first).
cd /d "%~dp0"
call "%~dp0_findpy.bat" || (pause & exit /b 1)
"%PYEXE%" %PYARGS% "%~dp0stop_hinata.py"
wscript "%~dp0start_hidden.vbs" 0
echo Hinata is restarting - give her about 20 seconds.
timeout /t 3 >nul
