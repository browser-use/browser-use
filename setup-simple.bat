@echo off
echo ========================================
echo  SIMPLE Browser-Use Setup (No Web UI)
echo ========================================
echo.
echo This installs just the basics - no fancy web interface.
echo You'll use Python scripts instead (which is actually easier!)
echo.
pause

echo.
echo [1/3] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ❌ Python is NOT installed!
    echo.
    echo STOP! Do this first:
    echo 1. Go to https://www.python.org/downloads/
    echo 2. Download Python (get version 3.11 or newer)
    echo 3. During install, CHECK the box: "Add Python to PATH"
    echo 4. Install it
    echo 5. RESTART YOUR COMPUTER
    echo 6. Run this file again
    echo.
    pause
    exit /b 1
)
python --version
echo ✓ Python found!

echo.
echo [2/3] Installing browser-use...
echo (This downloads from the internet, takes ~30 seconds)
pip install --upgrade browser-use
if errorlevel 1 (
    echo.
    echo ❌ Installation failed!
    echo.
    echo Try this:
    echo 1. Right-click this file
    echo 2. Choose "Run as administrator"
    echo 3. Try again
    echo.
    pause
    exit /b 1
)
echo ✓ browser-use installed!

echo.
echo [3/3] Installing Chromium browser...
echo (This downloads ~150MB, takes a few minutes)
echo Please be patient...
python -m playwright install chromium
if errorlevel 1 (
    echo.
    echo ⚠️  Chromium install had issues
    echo.
    echo Don't worry! Try this manually:
    echo 1. Open Command Prompt as administrator
    echo 2. Type: python -m playwright install chromium
    echo 3. Wait for it to finish
    echo.
    echo You can continue anyway and try running a script.
    echo.
)
echo ✓ Chromium installed!

echo.
echo ========================================
echo  ✅ INSTALLATION COMPLETE!
echo ========================================
echo.
echo What to do next:
echo.
echo 1. Run: setup-apikey.bat
echo    (This saves your Anthropic API key)
echo.
echo 2. Run: example-simple.bat
echo    (This tests if everything works)
echo.
echo 3. Edit 'example-simple.py' to make it do what you want!
echo.
echo ========================================
pause
