@echo off
cd /d "%~dp0"
chcp 866 >nul
title Qwen Orchestra
cls
echo.
echo  ========================================
echo   Qwen Orchestra  -  0.8b / 4b / 9b
echo  ========================================
echo.
echo   1) �થ��� (���� + �᪠����)
echo      python orchestra_chat.py
echo.
echo   2) ���� ����� �१ �થ���
echo      python ask_orchestra.py
echo.
echo   3) ��� 4b + ���୥�
echo      python chat_web.py
echo.
echo   4) ��� ⮫쪮 4b
echo      python chat.py
echo.
echo   5) Ollama: qwen3.5:4b
echo      ollama run qwen3.5:4b
echo.
echo   6) ���-�� (Cursor UI)
echo      python server.py
echo      http://127.0.0.1:8787
echo.
echo  ----------------------------------------
echo   �롥�� ����⢨�:
echo.

set /p choice="  ����� (1-6) ��� Enter ��� ��室�: "

if "%choice%"=="1" goto run1
if "%choice%"=="2" goto run2
if "%choice%"=="3" goto run3
if "%choice%"=="4" goto run4
if "%choice%"=="5" goto run5
if "%choice%"=="6" goto run6
goto end

:run1
echo.
python orchestra_chat.py
goto end

:run2
echo.
set /p q="  ������ �����: "
python ask_orchestra.py "%q%"
goto end

:run3
echo.
python chat_web.py
goto end

:run4
echo.
python chat.py
goto end

:run5
echo.
ollama run qwen3.5:4b
goto end

:run6
echo.
echo  ��ன� � ��㧥�: http://127.0.0.1:8787
echo  ��⠭����: Ctrl+C
echo.
python server.py
goto end

:end
echo.
pause
