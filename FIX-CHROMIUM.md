========================================
  QUICK FIX - Chromium/Playwright Issue
========================================

If you got "playwright not found" or "chromium install failed", do this:

STEP-BY-STEP FIX:
================

1. Press Windows key
   Type: cmd
   Right-click "Command Prompt"
   Choose "Run as administrator"

2. Copy and paste these commands ONE AT A TIME:

   pip install playwright

   (Wait for it to finish, then...)

   python -m playwright install chromium

   (This downloads ~150MB, takes 2-5 minutes)

   pip install browser-use

3. Done! Now run: setup-apikey.bat

========================================
ALTERNATIVE: Skip Chromium For Now
========================================

Want to test if everything else works first?

1. Skip the chromium install for now
2. Run: setup-apikey.bat (save your API key)
3. Edit example-simple.py and add this at the top:

   import os
   os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'

4. Run: example-simple.bat

5. If it asks to install chromium, let it do it automatically

========================================
STILL NOT WORKING?
========================================

The issue is usually one of these:

Problem: "Access denied"
Fix: Run Command Prompt as administrator

Problem: "Download failed" or timeout
Fix: Check your internet, disable antivirus temporarily, try again

Problem: "Space error"
Fix: You need ~200MB free space on C: drive

Problem: Takes forever and hangs
Fix: Cancel it (Ctrl+C), try again with better internet

========================================
NUCLEAR OPTION (Start Fresh)
========================================

If nothing works, start completely fresh:

1. Uninstall Python:
   - Settings → Apps → Python → Uninstall

2. Delete this folder:
   C:\Users\YourName\AppData\Local\ms-playwright

3. Restart computer

4. Install Python fresh:
   https://www.python.org/downloads/
   CHECK THE BOX: "Add Python to PATH"

5. Restart computer again

6. Run: setup-simple.bat

========================================
EASIEST SOLUTION
========================================

Honestly? Just use the cloud version:

https://cloud.browser-use.com

No installation, works in 2 minutes.
You can always install locally later!

========================================
