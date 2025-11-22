@echo off
echo ========================================
echo  Running Production Example
echo ========================================
echo.
echo This demonstrates:
echo - Vision enabled (agent can SEE the page)
echo - Proper task instructions
echo - Login handling
echo - Error debugging
echo.
echo BEFORE running this:
echo 1. Edit example-production.py
echo 2. Change the task to what you want
echo 3. Update login credentials if needed
echo.
pause

python example-production.py

echo.
echo ========================================
echo.
echo If it didn't work:
echo - Read PRODUCTION-GUIDE.md for troubleshooting
echo - Check agent_conversation.json to see what happened
echo.
pause
