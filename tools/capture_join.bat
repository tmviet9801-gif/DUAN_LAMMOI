@echo off
title Capture join template HITCLUB
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0capture_join.ps1"
pause
