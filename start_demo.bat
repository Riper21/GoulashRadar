@echo off
title Supplier Radar - Demo
echo Starting Supplier Radar (http://127.0.0.1:8000)...
echo Full warm-up: start_demo.bat full
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\start_demo.ps1" %*
pause

