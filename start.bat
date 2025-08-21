@echo off
cd /d %~dp0

echo [1/4] 检查 Python...
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
  echo ❌ 没有检测到 Python，请先安装 Python 3.11 或更新版本。
  pause
  exit /b 1
)

echo [2/4] 创建虚拟环境（如未存在）...
if not exist .venv (
  python -m venv .venv
)

echo [3/4] 激活虚拟环境并安装依赖...
call .venv\Scripts\activate.bat
pip install -U pip
pip install -r requirements.txt

echo [4/4] 启动应用...
set PYTHONPATH=.
if exist .env (
  echo 使用本地配置文件 .env
)
streamlit run ui\web.py
pause
