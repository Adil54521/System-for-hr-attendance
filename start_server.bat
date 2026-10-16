@echo off
chcp 65001 > nul
cd /d "C:\HR"
call venv\Scripts\activate.bat
cd hr_attendance_project
python serve.py