@echo off
echo ========================================
echo  Starting Browser-Use Web Interface
echo ========================================
echo.

REM Check if browser-use CLI is installed
browser-use --help >nul 2>&1
if errorlevel 1 (
    echo ERROR: browser-use CLI is not installed!
    echo.
    echo Please run setup-windows.bat first
    echo.
    echo OR install manually:
    echo   pip install "browser-use[cli]"
    echo.
    pause
    exit /b 1
)

echo Opening web interface in your browser...
echo.
echo TIP: The interface will open at http://localhost:8000
echo Press Ctrl+C to stop the server when done.
echo.
echo ========================================
echo.

browser-use
