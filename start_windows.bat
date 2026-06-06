@echo off
setlocal
cd /d "%~dp0"

rem 开发/备用启动脚本：
rem 1. 用户电脑已安装 Python 时，首次运行会自动创建 .venv 并安装依赖。
rem 2. 真正发给普通用户时，更推荐使用 build_windows.ps1 打包出的免安装 exe。

where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON=py -3"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PYTHON=python"
  ) else (
    echo 未找到 Python。请安装 Python 3.11+，或使用打包版 SkinPsdAdapter.exe。
    pause
    exit /b 1
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo 正在创建本地 Python 环境...
  %PYTHON% -m venv .venv
  if %errorlevel% neq 0 (
    echo 创建虚拟环境失败。
    pause
    exit /b 1
  )
)

echo 正在安装/检查依赖...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if %errorlevel% neq 0 (
  echo 依赖安装失败。请检查网络或改用免安装打包版。
  pause
  exit /b 1
)

echo 正在启动工具...
".venv\Scripts\python.exe" start.py
pause

