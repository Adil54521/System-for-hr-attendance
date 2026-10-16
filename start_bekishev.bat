@echo off
chcp 65001 > nul
cd /d "C:\HR\hr_attendance_project"
call venv\Scripts\activate.bat
python manage.py bekishev > Bekishev.log 2>&1
