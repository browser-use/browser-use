"""
Chrome profile persistence layer for Comet.
Launches browser-use with the user's real Chrome profile on Windows 10/11.
Zero 2FA — zero Captcha — already logged-in sessions inherited automatically.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def get_chrome_user_data_dir() -> str:
    """
    Return the path to the real Chrome User Data directory on Windows.
    Falls back to env var CHROME_USER_DATA_DIR if set.
    """
    env_override = os.environ.get("CHROME_USER_DATA_DIR", "")
    if env_override and Path(env_override).exists():
        return env_override

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        # Fallback for edge cases
        local_app_data = str(Path.home() / "AppData" / "Local")

    path = Path(local_app_data) / "Google" / "Chrome" / "User Data"
    return str(path)


def get_chrome_executable() -> str | None:
    """
    Return the path to chrome.exe on Windows 10/11.
    Returns None if not found (Playwright will use bundled Chromium).
    """
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            r"Google\Chrome\Application\chrome.exe"
        ),
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def get_persistent_context_kwargs(profile: str = "Default") -> dict:
    """
    Build the kwargs dict for Playwright's launch_persistent_context.

    Usage in browser-use custom browser:
        from comet.utils.chrome_profile import get_persistent_context_kwargs
        kwargs = get_persistent_context_kwargs()
        context = await playwright.chromium.launch_persistent_context(**kwargs)
    """
    user_data_dir = get_chrome_user_data_dir()
    executable    = get_chrome_executable()

    kwargs: dict = {
        "user_data_dir": user_data_dir,
        "headless":      False,
        "channel":       "chrome",          # use installed Chrome, not Chromium
        "args": [
            f"--profile-directory={profile}",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--window-size=1280,800",
        ],
        "ignore_default_args": ["--enable-automation"],
        "accept_downloads":    True,
    }

    if executable:
        kwargs["executable_path"] = executable

    return kwargs
