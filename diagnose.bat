@echo off
echo ========================================
echo  Browser-Use Setup Diagnostic Tool
echo ========================================
echo.
echo This will check what's wrong with your setup.
echo.
pause

echo.
echo [1/5] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ PROBLEM: Python is NOT installed
    echo.
    echo FIX: Install Python from https://www.python.org/downloads/
    echo      Make sure to check "Add Python to PATH" during installation!
    echo.
    set HAS_PYTHON=0
) else (
    echo ✓ Python is installed
    python --version
    set HAS_PYTHON=1
)

echo.
echo [2/5] Checking pip (Python package installer)...
pip --version >nul 2>&1
if errorlevel 1 (
    echo ❌ PROBLEM: pip is NOT working
    echo.
    echo FIX: Reinstall Python and make sure pip is included
    echo.
    set HAS_PIP=0
) else (
    echo ✓ pip is working
    pip --version
    set HAS_PIP=1
)

echo.
echo [3/5] Checking internet connection...
ping google.com -n 1 >nul 2>&1
if errorlevel 1 (
    echo ❌ PROBLEM: No internet connection
    echo.
    echo FIX: Connect to the internet and try again
    echo.
    set HAS_INTERNET=0
) else (
    echo ✓ Internet connection working
    set HAS_INTERNET=1
)

echo.
echo [4/5] Checking if browser-use is installed...
pip show browser-use >nul 2>&1
if errorlevel 1 (
    echo ⚠️  browser-use is NOT installed yet
    echo    (This is normal if you haven't run setup-windows.bat)
    echo.
    set HAS_BROWSERUSE=0
) else (
    echo ✓ browser-use is already installed
    pip show browser-use | findstr "Version"
    set HAS_BROWSERUSE=1
)

echo.
echo [5/5] Checking for API key...
if exist "%USERPROFILE%\.env" (
    echo ✓ .env file found at %USERPROFILE%\.env
    findstr "ANTHROPIC_API_KEY" "%USERPROFILE%\.env" >nul 2>&1
    if errorlevel 1 (
        echo ⚠️  But it doesn't have ANTHROPIC_API_KEY in it
        set HAS_APIKEY=0
    ) else (
        echo ✓ API key appears to be configured
        set HAS_APIKEY=1
    )
) else (
    echo ⚠️  No .env file found
    echo    (This is normal if you haven't run setup-apikey.bat)
    set HAS_APIKEY=0
)

echo.
echo ========================================
echo  DIAGNOSIS COMPLETE
echo ========================================
echo.

if "%HAS_PYTHON%"=="0" (
    echo ❌ INSTALL PYTHON FIRST
    echo    Go to: https://www.python.org/downloads/
    echo    Check "Add Python to PATH" during install
    echo    Then restart your computer
    echo.
    goto :end
)

if "%HAS_PIP%"=="0" (
    echo ❌ FIX PIP INSTALLATION
    echo    Reinstall Python with pip included
    echo.
    goto :end
)

if "%HAS_INTERNET%"=="0" (
    echo ❌ CONNECT TO INTERNET
    echo    You need internet to download packages
    echo.
    goto :end
)

if "%HAS_BROWSERUSE%"=="0" (
    echo ✅ READY TO INSTALL
    echo    Next step: Run setup-windows.bat
    echo.
    goto :end
)

if "%HAS_APIKEY%"=="0" (
    echo ✅ READY TO CONFIGURE API KEY
    echo    Next step: Run setup-apikey.bat
    echo.
    goto :end
)

echo ✅ EVERYTHING LOOKS GOOD!
echo    Next step: Run start-ui.bat to launch the interface
echo.

:end
echo ========================================
pause
