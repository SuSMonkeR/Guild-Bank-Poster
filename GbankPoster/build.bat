@echo off
:: ════════════════════════════════════════════════════════════════════
::  GBank Poster — Build Script
::  Produces:  dist\GBankPoster.exe
::
::  Requirements: Python 3.11+  (https://python.org)
::  Usage: Double-click this file, or run from a command prompt.
:: ════════════════════════════════════════════════════════════════════

title GBank Poster — Build

echo.
echo ╔══════════════════════════════════╗
echo ║    GBank Poster — Building EXE   ║
echo ╚══════════════════════════════════╝
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH.
    echo Install Python 3.11+ from https://python.org and try again.
    pause & exit /b 1
)

echo [1/4] Installing dependencies...
pip install --upgrade pyinstaller pillow pystray tkinterdnd2 colorsys 2>nul
pip install --upgrade pyinstaller pillow pystray tkinterdnd2 >nul 2>&1
if errorlevel 1 (
    echo ERROR: pip failed. Try running as Administrator.
    pause & exit /b 1
)

echo [2/4] Cleaning previous build...
if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist

echo [3/4] Building GBankPoster.exe...
pyinstaller GBankPoster.spec
if errorlevel 1 (
    echo.
    echo BUILD FAILED — check output above for errors.
    pause & exit /b 1
)

echo [4/4] Done!
echo.
echo ════════════════════════════════════════════════
echo  Output:  dist\GBankPoster.exe
echo.
echo  The EXE is fully self-contained.
echo  Copy it anywhere — config files are created
echo  next to the EXE on first run.
echo ════════════════════════════════════════════════
echo.
pause
