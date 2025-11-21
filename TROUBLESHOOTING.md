# 🔧 Troubleshooting Guide

## Step 0: Run the Diagnostic Tool First!

**Double-click `diagnose.bat`** - it will tell you exactly what's wrong.

Then come back here for the fix.

---

## Common Problems & Solutions

### ❌ "Python is not recognized" or "python is not a command"

**What this means:** Python isn't installed, or Windows can't find it.

**Fix:**
1. Download Python: https://www.python.org/downloads/
2. Run the installer
3. **CRITICAL**: ✅ Check the box "Add Python to PATH" at the bottom
4. Click "Install Now"
5. **Restart your computer** (yes, really!)
6. Try again

**Still not working?**
- Uninstall Python completely
- Restart computer
- Install again, making SURE to check "Add Python to PATH"

---

### ❌ Batch file flashes and closes immediately

**What this means:** There's an error, but you can't see it because the window closes.

**Fix - See the error:**
1. Press Windows key
2. Type `cmd` and press Enter
3. Type: `cd Downloads\browser-use-JT` (or wherever you put the folder)
4. Type: `setup-windows.bat`
5. Now you can see the error!

**Or make it stay open:**
1. Right-click the `.bat` file
2. Click "Edit"
3. Add this line at the very end:
   ```
   pause
   ```
4. Save and run again

---

### ❌ "Access Denied" or "Permission Error"

**What this means:** Windows won't let you install stuff.

**Fix:**
1. Right-click the `.bat` file
2. Choose "Run as administrator"
3. Click "Yes" when Windows asks

**Still not working?**
- Check if antivirus is blocking it
- Temporarily disable antivirus
- Try again
- Re-enable antivirus

---

### ❌ "playwright install" fails or hangs

**What this means:** The browser download is having trouble.

**Fix Option 1 - Manual install:**
1. Open Command Prompt as administrator
2. Type: `pip install playwright`
3. Type: `playwright install chromium`
4. Wait (this downloads ~150MB, takes a few minutes)

**Fix Option 2 - Skip it for now:**
1. Just install browser-use: `pip install browser-use`
2. Run your script - it will tell you to install playwright
3. Follow its instructions

---

### ❌ "No module named 'browser_use'"

**What this means:** Installation didn't work.

**Fix:**
1. Open Command Prompt as administrator
2. Type: `pip install --upgrade browser-use`
3. Try again

**If that doesn't work:**
1. Type: `pip uninstall browser-use`
2. Type: `pip install browser-use`
3. Try again

---

### ❌ "API key not found" when running scripts

**What this means:** The .env file isn't in the right place or is wrong.

**Fix Option 1 - Check the file:**
1. Press Windows key + R
2. Type: `%USERPROFILE%`
3. Press Enter
4. Look for `.env` file
5. Right-click → Open with Notepad
6. Make sure it says exactly:
   ```
   ANTHROPIC_API_KEY=sk-ant-your-key-here
   ```
   (No spaces, no quotes, your actual key)

**Fix Option 2 - Create it manually:**
1. Open Notepad
2. Type: `ANTHROPIC_API_KEY=sk-ant-your-actual-key-here`
3. Save as `.env` in `C:\Users\YourName\`
4. In "Save as type" choose "All Files"
5. Make sure filename is exactly `.env` (not `.env.txt`)

**Fix Option 3 - Put it next to your script:**
1. Copy the `.env` file
2. Put it in the same folder as your Python script
3. Try again

---

### ❌ "start-ui.bat" does nothing or shows error

**What this means:** browser-use CLI isn't installed.

**Fix:**
1. Open Command Prompt as administrator
2. Type: `pip install "browser-use[cli]"`
3. Wait for it to finish
4. Try running `start-ui.bat` again

**Still not working?**
Try running it manually:
1. Open Command Prompt
2. Type: `browser-use`
3. See what error it shows
4. Send me that error message!

---

### ❌ Browser opens but nothing happens

**What this means:** API key might be wrong, or no internet.

**Check:**
1. Is your internet working? (Try loading a website)
2. Is your API key correct?
   - Go to https://console.anthropic.com/
   - Check if it starts with `sk-ant-`
   - Copy it again fresh
   - Run `setup-apikey.bat` again

**Still stuck?**
Try the test script:
1. Run `example-simple.bat`
2. Look at the error message
3. Google that error, or ask in Discord: https://link.browser-use.com/discord

---

### ❌ "Rate limit exceeded"

**What this means:** You're using the API too fast or too much.

**Fix:**
1. Wait 60 seconds
2. Try again
3. If it keeps happening, you might have hit your daily limit
4. Check your Anthropic dashboard: https://console.anthropic.com/

---

### ❌ "This app can't run on your PC"

**What this means:** Wrong Windows version or missing system files.

**Fix:**
1. Make sure you're on Windows 10 or 11 (not Windows 7/8)
2. Update Windows:
   - Settings → Update & Security → Check for updates
3. Install Visual C++ Redistributable:
   - Download from: https://aka.ms/vs/17/release/vc_redist.x64.exe
   - Install it
   - Restart computer

---

### ❌ "SSL Certificate Error"

**What this means:** Your computer's security certificates are out of date.

**Fix:**
1. Update Windows completely
2. Or try: `pip install --upgrade certifi`
3. Or add this to your script at the top:
   ```python
   import ssl
   ssl._create_default_https_context = ssl._create_unverified_context
   ```

---

### ❌ Still Stuck?

**Last resort options:**

**Option 1 - Use the cloud version instead:**
- Go to https://cloud.browser-use.com
- No installation needed
- Works immediately

**Option 2 - Get help:**
- Discord: https://link.browser-use.com/discord
- Post your error message
- Someone will help!

**Option 3 - Fresh start:**
1. Delete the browser-use-JT folder
2. Restart your computer
3. Download it again
4. Run `diagnose.bat` first
5. Follow what it says

---

## 📝 How to Get Good Help

If you need to ask for help, provide:

1. **What you were trying to do**: "I ran setup-windows.bat"
2. **What happened**: "A black window appeared then closed"
3. **Error message**: Copy/paste the exact text
4. **What you already tried**: "I ran as administrator"
5. **Your setup**: "Windows 11, Python 3.12"

**Good example:**
```
I'm trying to run setup-windows.bat on Windows 11.
It says "pip is not recognized".
I already installed Python 3.12 and checked "Add to PATH".
I restarted my computer but still get the same error.
```

**Bad example:**
```
It doesn't work
```

---

## 🎯 Prevention Tips

**Before you start:**
1. ✅ Install Python with "Add to PATH" checked
2. ✅ Restart computer after installing Python
3. ✅ Run Command Prompt as administrator
4. ✅ Disable antivirus temporarily
5. ✅ Have good internet connection
6. ✅ Get your API key from Anthropic first

**Do this and you'll avoid 90% of problems!**

---

Made with ❤️ - we've all been there, don't give up!
