@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
python -u -m workbench.server --open
if errorlevel 1 pause
