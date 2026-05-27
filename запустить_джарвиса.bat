@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Загрузка переменных из .env...
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" if not "%%B"=="" (
        set "%%A=%%B"
    )
)

echo Проверка зависимостей...
python -m pip install -q python-telegram-bot anthropic

echo.
echo ==========================================
echo   Джарвис — Главный Инженер Проекта
echo ==========================================
echo.
python jarvis_bot.py
pause
