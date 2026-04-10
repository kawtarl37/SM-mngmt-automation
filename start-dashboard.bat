@echo off
echo Starting the Easy Gluten Free Dashboard...

cd /d "C:\Users\HP\Documents\automation-EGF"

IF EXIST "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) ELSE (
    echo [WARNING] Virtual environment 'venv' not found. Ensure it is created and activated.
)

python execution\dashboard.py

pause
