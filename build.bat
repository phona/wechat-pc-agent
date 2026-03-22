@echo off
setlocal

if not defined PYTHON (
    where python >nul 2>nul
    if errorlevel 1 (
        where py >nul 2>nul
        if errorlevel 1 (
            echo ERROR: Could not find a usable Python interpreter
            exit /b 1
        )
        set "PYTHON=py"
    ) else (
        set "PYTHON=python"
    )
)

echo === Building WeChat Agent portable package ===
echo.
%PYTHON% --version
if errorlevel 1 (
    echo ERROR: Failed to run %PYTHON%
    exit /b 1
)
echo.

REM Install build dependencies
%PYTHON% -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo ERROR: Failed to install base build tooling
    exit /b 1
)

%PYTHON% -m pip install pyinstaller pyautogui Pillow PyQt6 httpx websockets pydantic numpy pyperclip
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    exit /b 1
)

REM Build with PyInstaller
%PYTHON% -m PyInstaller build.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed
    exit /b 1
)

if not exist dist\WeChat-Agent\WeChat-Agent.exe (
    echo ERROR: Expected dist\WeChat-Agent\WeChat-Agent.exe was not created
    exit /b 1
)

REM Create release folder
if exist release\WeChat-Agent rmdir /s /q release\WeChat-Agent
mkdir release\WeChat-Agent

REM Copy built files
xcopy /E /I /Y dist\WeChat-Agent\* release\WeChat-Agent\
if errorlevel 1 (
    echo ERROR: Failed to copy build output into release\WeChat-Agent
    exit /b 1
)

REM Copy config template
copy /Y config.example.json release\WeChat-Agent\config.json
if errorlevel 1 (
    echo ERROR: Failed to copy config template
    exit /b 1
)

echo.
echo === Build complete ===
echo Output: release\WeChat-Agent\
echo.
echo Next steps:
echo   1. Edit release\WeChat-Agent\config.json with your server URL and token
echo   2. Copy the WeChat-Agent folder to the target Windows PC
echo   3. Run WeChat-Agent.exe (requires admin + WeChat running)
