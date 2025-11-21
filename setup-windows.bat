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
echo This may take a few minutes and download ~150MB...
playwright install chromium
if errorlevel 1 (
    echo.
    echo WARNING: Chromium install had issues, trying alternative method...
    python -m playwright install chromium
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to install Chromium
        echo You can try manually: python -m playwright install chromium
        pause
        exit /b 1
    )
)
echo ✓ Chromium installed!

echo.
echo Step 4: Installing CLI interface...
pip install "browser-use[cli]"
if errorlevel 1 (
    echo WARNING: CLI installation had issues
    echo You can still use Python scripts, just not the web UI
)
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
