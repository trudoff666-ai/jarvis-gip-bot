@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Загрузка переменных из .env...
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" if not "%%B"=="" (
        set "%%A=%%B"
    )
)

set PYTHON=C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe

echo Проверка зависимостей...
"%PYTHON%" -m pip install -q python-telegram-bot anthropic

echo.
echo ==========================================
echo   Джарвис — Главный Инженер Проекта
echo ==========================================
echo.
"%PYTHON%" jarvis_bot.py
pause
