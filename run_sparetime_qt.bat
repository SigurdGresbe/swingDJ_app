@echo off
setlocal
cd /d "%~dp0"
set "STUDIO_PYTHON="
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)"') do set "STUDIO_PYTHON=%%P"
if not defined STUDIO_PYTHON (
    echo Python was not found. Install Python and try again.
    pause
    exit /b 1
)
"%STUDIO_PYTHON%" -c "import PySide6, pandas, openpyxl, xlrd, spotipy" >nul 2>&1
if errorlevel 1 (
    echo Installing required packages...
    "%STUDIO_PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Installation failed. The app was not started.
        pause
        exit /b 1
    )
)
for %%P in ("%STUDIO_PYTHON%") do set "STUDIO_PYTHONW=%%~dpPpythonw.exe"
if not exist "%STUDIO_PYTHONW%" (
    echo pythonw.exe was not found beside the selected Python installation.
    pause
    exit /b 1
)
start "SpareTime Studio" "%STUDIO_PYTHONW%" "%~dp0main.py"
exit /b
