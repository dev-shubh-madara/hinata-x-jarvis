@echo off
cd /d "%~dp0"
call "%~dp0_findpy.bat" || (pause & exit /b 1)
echo Using: %PYEXE% %PYARGS%
echo Installing Hinata X Helper dependencies...
"%PYEXE%" %PYARGS% -m pip install --disable-pip-version-check -r requirements.txt
echo.
echo Done. Make sure Ollama is installed, then run: ollama pull qwen2.5:3b
pause
