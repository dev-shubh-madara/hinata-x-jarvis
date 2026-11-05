@echo off
rem Makes Hinata X Helper start automatically every time you log in to Windows.
setlocal
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LAUNCHER=%STARTUP%\Hinata X Helper.vbs"
(
  echo ' Starts Hinata X Helper at login - created by install_autostart.bat
  echo CreateObject^("WScript.Shell"^).Run """%~dp0start_hidden.vbs""", 0, False
) > "%LAUNCHER%"
if exist "%LAUNCHER%" (
  echo.
  echo  Done! Hinata X Helper will now start by herself every time you log in.
  echo  She starts about 15 seconds after login, with no black window.
  echo  To turn this off, run uninstall_autostart.bat
) else (
  echo  Could not write to the Startup folder: %STARTUP%
)
echo.
pause
