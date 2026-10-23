@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "dist\v0.1.2\justVedio\justVedio.exe" (
  start "" "dist\v0.1.2\justVedio\justVedio.exe"
  exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "main.py"
  exit /b
)
echo 请先按 README.md 安装 Python 依赖，或运行完整的 EXE 包。
pause
