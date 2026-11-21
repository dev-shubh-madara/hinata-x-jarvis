@echo off
rem One-click setup for Hinata 2.x: stops old copies, installs, tests the GPU speech, auto-start, starts her.
title Hinata X Helper - setup
cd /d "%~dp0"
set "LOG=%~dp0setup_v2_log.txt"
echo Hinata setup %date% %time% > "%LOG%"

echo [1/6] Stopping every running Hinata / Jarvis...
call "%~dp0_findpy.bat" >> "%LOG%" 2>&1 || (echo Python not found - see setup_v2_log.txt & pause & exit /b 1)
echo Python: %PYEXE% %PYARGS% >> "%LOG%"
"%PYEXE%" %PYARGS% "%~dp0stop_hinata.py" >> "%LOG%" 2>&1

echo [2/6] Checking Windows startup for duplicate launchers...
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "OLD=%APPDATA%\HinataOldLaunchers"
powershell -NoProfile -Command "$s=$env:STARTUP; $o=$env:OLD; Get-ChildItem -LiteralPath $s | ForEach-Object { 'startup item: ' + $_.Name; if ($_.Name -ne 'Hinata X Helper.vbs' -and ($_.Name -match 'jarvis|hinata|shubh x|helper' -or ((Get-Content -LiteralPath $_.FullName -Raw -ErrorAction SilentlyContinue) -match 'jarvis'))) { New-Item -ItemType Directory -Force -Path $o | Out-Null; Move-Item -LiteralPath $_.FullName -Destination $o -Force; '  -> moved to ' + $o } }" >> "%LOG%" 2>&1

echo [3/6] Installing packages (first time takes a few minutes)...
"%PYEXE%" %PYARGS% -m pip install --disable-pip-version-check -r requirements.txt >> "%LOG%" 2>&1
echo pip exit code %errorlevel% >> "%LOG%"

echo [4/6] Testing the microphone, wake word and speech on your GPU...
"%PYEXE%" %PYARGS% -c "import faster_whisper, webrtcvad, sherpa_onnx, pyaudio; print('PACKAGES OK')" >> "%LOG%" 2>&1
"%PYEXE%" %PYARGS% -c "import fast_stt; m=fast_stt.load_whisper(); print('WHISPER', 'OK' if m else 'FAILED'); print('MIC', 'OK' if fast_stt.mic().start() else 'FAILED ' + fast_stt.mic().error)" >> "%LOG%" 2>&1

echo [5/6] Turning on auto-start at login...
(
  echo ' Starts Hinata X Helper at login - created by setup_hinata_v2.bat
  echo CreateObject^("WScript.Shell"^).Run """%~dp0start_hidden.vbs""", 0, False
) > "%STARTUP%\Hinata X Helper.vbs"
if exist "%STARTUP%\Hinata X Helper.vbs" (echo autostart OK >> "%LOG%") else (echo autostart FAILED >> "%LOG%")

echo [6/6] Starting Hinata...
wscript "%~dp0start_hidden.vbs" 0
echo started >> "%LOG%"
echo SETUP DONE >> "%LOG%"
echo.
echo Done. Give her about 30 seconds, then say: "Hinata, open Notepad".
timeout /t 6 >nul
