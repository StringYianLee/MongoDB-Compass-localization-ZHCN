@echo off
cd /d "%~dp0"
echo 正在还原 MongoDB Compass 英文原版...
python "%~dp0CompassZhCn.py" --restore --kill
echo.
echo 操作结束。请按任意键关闭窗口。
pause >nul
