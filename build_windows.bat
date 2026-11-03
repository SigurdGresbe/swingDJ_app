@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements.txt
pyside6-deploy main.py --name SpareTimeStudio --extra-ignore-dirs=generated,tests --force
if errorlevel 1 pause
