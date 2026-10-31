@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (py -3 instalar.py) || (python instalar.py)
if errorlevel 1 echo. & echo   Nao achei o Python. Instale em https://www.python.org/downloads/ (marque "Add python.exe to PATH").
pause
