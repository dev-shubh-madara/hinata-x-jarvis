@echo off
rem Stops Hinata X Helper from starting automatically at login.
set "LAUNCHER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Hinata X Helper.vbs"
if exist "%LAUNCHER%" del "%LAUNCHER%"
echo  Autostart is off. You can still start Hinata with run.bat.
pause
