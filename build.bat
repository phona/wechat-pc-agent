@echo off
echo === Building WeChat Agent portable package ===
echo.

REM Install build dependencies
pip install pyinstaller pyautogui wxauto wdecipher pydantic PyQt6 httpx websockets
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    exit /b 1
)

REM Build with PyInstaller
pyinstaller build.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed
    exit /b 1
)

REM Create release folder
if exist release\WeChat-Agent rmdir /s /q release\WeChat-Agent
mkdir release\WeChat-Agent

REM Copy built files
xcopy /E /I dist\WeChat-Agent\* release\WeChat-Agent\

REM Copy config template
copy config.example.json release\WeChat-Agent\config.json

echo.
echo === Build complete ===
echo Output: release\WeChat-Agent\
echo.
echo Next steps:
echo   1. Edit release\WeChat-Agent\config.json with your server URL and token
echo   2. Copy the WeChat-Agent folder to the target Windows PC
echo   3. Run WeChat-Agent.exe (requires admin + WeChat running)
