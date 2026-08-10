@echo off
rem Ярлык запуска. Запускать надо именно этот файл или kmd_app.py,
rem а не файл ui.py внутри папки kmd - иначе не сработает
cd /d "%~dp0"
python "%~dp0kmd_app.py" %*
if errorlevel 1 pause
