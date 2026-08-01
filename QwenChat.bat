@echo off
cd /d "%~dp0"
chcp 866 >nul
title Qwen Chat
python open_web.py
if errorlevel 1 pause
