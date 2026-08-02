@echo off
cd /d "%~dp0"
chcp 866 >nul
title Qwen Chat
if exist "%~dp0QwenChat.exe" (
  "%~dp0QwenChat.exe" %*
) else (
  python open_web.py %*
)
if errorlevel 1 pause
