@echo off
chcp 65001
title Запуск Attendance Bot

echo Начинаем запуск бота...

:: Переходим в корень проекта
cd /d "C:\HR\HR\hr_attendance_project"
echo Находимся в директории проекта: %CD%

:: Активируем виртуальное окружение
call ..\venv\Scripts\activate
echo Виртуальное окружение активировано

:: Запускаем бота
echo Пробуем запустить Python
python -m bot.main
if ERRORLEVEL 1 (
    echo Произошла ошибка при запуске бота
) else (
    echo Бот запущен успешно
)

echo Скрипт завершен
