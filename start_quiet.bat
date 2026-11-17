@echo off
rem Starts Hinata X Helper with no console window (uses pythonw).
cd /d "%~dp0"
call "%~dp0_findpy.bat" || (pause & exit /b 1)
if /i "%PYEXE%"=="py" (
  start "" pyw %PYARGS% "%~dp0main.py"
) else if /i "%PYEXE%"=="python" (
  start "" pythonw "%~dp0main.py"
) else (
  start "" "%PYEXE:python.exe=pythonw.exe%" "%~dp0main.py"
)
