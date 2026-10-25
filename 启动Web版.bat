@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0.fletvenv\Scripts\pythonw.exe" (
    start "" "%~dp0.fletvenv\Scripts\pythonw.exe" "%~dp0web_app.py"
    exit /b
)

py -3 -c "import flet" >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 "%~dp0web_app.py"
    exit /b
)

python -c "import flet" >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0web_app.py"
    exit /b
)

echo.
echo [ERROR] Flet not installed.
echo Run: pip install -r requirements.txt
echo Or double-click dist_flet\CompassZhCnWeb.exe (standalone web server).
echo.
pause
