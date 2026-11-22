@echo off
cd /d "%~dp0"
call "%~dp0_findpy.bat" || (pause & exit /b 1)
"%PYEXE%" %PYARGS% "%~dp0preview_caption_bar.py" > "%~dp0preview_log.txt" 2>&1
