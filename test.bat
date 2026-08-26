@echo off
title Run tests - Tab Manager
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0test.ps1"
pause
