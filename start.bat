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
echo   1) Оркестр (чат + эскалация)
echo      python orchestra_chat.py
echo.
echo   2) Один вопрос через оркестр
echo      python ask_orchestra.py
echo.
echo   3) Чат 4b + интернет
echo      python chat_web.py
echo.
echo   4) Чат только 4b
echo      python chat.py
echo.
echo   5) Ollama: qwen3.5:4b
echo      ollama run qwen3.5:4b
echo.
echo   6) Веб-чат локально
echo      python server.py
echo      http://127.0.0.1:8787
echo.
echo   7) Веб-чат открыт в сеть (share)
echo      python server.py --share
echo.
echo  ----------------------------------------
echo   Выберите действие:
echo.

set /p choice="  Номер (1-7) или Enter для выхода: "

if "%choice%"=="1" goto run1
if "%choice%"=="2" goto run2
if "%choice%"=="3" goto run3
if "%choice%"=="4" goto run4
if "%choice%"=="5" goto run5
if "%choice%"=="6" goto run6
if "%choice%"=="7" goto run7
goto end

:run1
echo.
python orchestra_chat.py
goto end

:run2
echo.
set /p q="  Ваш вопрос: "
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
echo  Сервер: http://127.0.0.1:8787
echo  Остановка: Ctrl+C
echo.
python server.py
goto end

:run7
echo.
echo  SHARE: слушаем 0.0.0.0:8787
echo  Локально: http://127.0.0.1:8787
echo  Остановка: Ctrl+C
echo.
set /p tok="  Пароль для гостя (пусто = без): "
if "%tok%"=="" (
  python server.py --share
) else (
  python server.py --share --token "%tok%"
)
goto end

:end
echo.
pause
