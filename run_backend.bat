@echo off
chcp 65001 >nul
title AutoTool Backend
cd /d "%~dp0backend"
echo [AutoTool] Khoi dong Backend...
.venv\Scripts\python.exe main.py
pause
