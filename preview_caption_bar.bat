@echo off
cd /d "%~dp0"
call "%~dp0_findpy.bat" || (pause & exit /b 1)
start "" "%PYEXE%" %PYARGS% "%~dp0preview_caption_bar.py"
