@echo off
title Sinh license AutoTool (owner)
echo.
echo === SINH LICENSE KEY ===
set /p DAYS="So ngay hieu luc [30]: "
if "%DAYS%"=="" set DAYS=30
set /p TABS="Gioi han tab [10]: "
if "%TABS%"=="" set TABS=10
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%~dp0backend\.venv\Scripts\python.exe' '%~dp0backend\tools\make_license.py' --days %DAYS% --max-tabs %TABS%"
echo.
pause
