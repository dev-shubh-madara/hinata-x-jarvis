@echo off
title Hinata X Helper - installing the update
cd /d "%~dp0"
call "%~dp0_findpy.bat" || (pause & exit /b 1)
echo Installing the new parts (wake word, fast speech, memory, browser, plug-ins)...
"%PYEXE%" %PYARGS% -m pip install --disable-pip-version-check -r requirements.txt > update_log.txt 2>&1
"%PYEXE%" %PYARGS% -c "import uiautomation, playwright, imageio_ffmpeg; print('NEW PARTS OK', imageio_ffmpeg.get_ffmpeg_exe())" >> update_log.txt 2>&1
"%PYEXE%" %PYARGS% -c "import faster_whisper, webrtcvad, sherpa_onnx; print('2.0 PARTS OK')" >> update_log.txt 2>&1
"%PYEXE%" %PYARGS% tests\run_all.py >> update_log.txt 2>&1
del /q _wa_probe.py _wa_probe.bat wa_probe.log wa_pip.log 2>nul
echo Restarting Hinata...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
timeout /t 2 >nul
wscript "%~dp0start_hidden.vbs"
echo DONE >> update_log.txt
echo.
echo Update installed. Hinata is starting again - give her about 30 seconds.
timeout /t 8 >nul
