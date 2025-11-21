@echo off
echo ========================================
echo  Browser-Use Auto Setup for Windows
echo ========================================
echo.
echo This will install everything you need!
echo.
pause

echo.
echo Step 1: Checking if Python is installed...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Python is not installed!
    echo Please install Python from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation!
    echo.
    pause
    exit /b 1
)
echo ✓ Python is installed!

echo.
echo Step 2: Installing browser-use...
pip install browser-use
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install browser-use
    pause
    exit /b 1
)
echo ✓ browser-use installed!

echo.
echo Step 3: Installing browser (Chromium)...
playwright install chromium --with-deps --no-shell
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install Chromium
    pause
    exit /b 1
)
echo ✓ Chromium installed!

echo.
echo Step 4: Installing CLI interface...
pip install browser-use[cli]
echo ✓ CLI installed!

echo.
echo ========================================
echo  ✓ Installation Complete!
echo ========================================
echo.
echo Next steps:
echo 1. Get your Anthropic API key from https://console.anthropic.com/
echo 2. Run the setup wizard: setup-apikey.bat
echo.
pause
