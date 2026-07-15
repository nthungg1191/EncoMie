@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ==================================================
echo             Auto Video Editor Packager
echo ==================================================
echo.

:: 1. Check for Virtual Environment
set "VENV_PATH="
if exist ".venv\Scripts\activate.bat" (
    set "VENV_PATH=.venv"
) else if exist "venv\Scripts\activate.bat" (
    set "VENV_PATH=venv"
)

if defined VENV_PATH (
    echo [INFO] Kích hoạt môi trường ảo từ !VENV_PATH!...
    call "!VENV_PATH!\Scripts\activate.bat"
) else (
    echo [INFO] Không tìm thấy môi trường ảo. Sử dụng Python hệ thống...
)

:: 2. Run packaging script
echo [INFO] Bắt đầu đóng gói ứng dụng...
python build.py %*

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Đóng gói thất bại với mã lỗi %errorlevel%.
    pause
    exit /b %errorlevel%
)

echo.
echo [INFO] Đóng gói hoàn tất!
pause
endlocal
