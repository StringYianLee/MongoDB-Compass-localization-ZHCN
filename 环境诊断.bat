@echo off
cd /d "%~dp0"
echo ============================================
echo   MongoDB Compass 汉化工具 - 环境诊断
echo ============================================
python --version
echo.
python "%~dp0CompassZhCn.py" --status
echo.
python "%~dp0CompassZhCn.py" --backups
echo.
echo 日志目录: %LOCALAPPDATA%\CompassZhCn\logs
pause >nul
