@echo off
echo ========================================
echo  API Key Setup Wizard
echo ========================================
echo.
echo This will save your Anthropic API key securely.
echo.
echo To get your API key:
echo 1. Go to https://console.anthropic.com/
echo 2. Click "API Keys"
echo 3. Click "Create Key"
echo 4. Copy the key (starts with sk-ant-)
echo.

set /p api_key="Paste your API key here and press Enter: "

if "%api_key%"=="" (
    echo.
    echo ERROR: No API key entered!
    pause
    exit /b 1
)

echo ANTHROPIC_API_KEY=%api_key%> "%USERPROFILE%\.env"

echo.
echo ✓ API key saved to %USERPROFILE%\.env
echo.
echo ========================================
echo  ✓ Setup Complete!
echo ========================================
echo.
echo You can now run the browser automation!
echo.
echo Quick start options:
echo 1. Run 'start-ui.bat' for a web interface
echo 2. Run 'example-simple.bat' to see it in action
echo.
pause
