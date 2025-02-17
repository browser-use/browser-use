import sys

def get_screen_resolution():
    if sys.platform == "darwin":  # Correct check for macOS
        try:
            from AppKit import NSScreen  # macOS-only import
            screen = NSScreen.mainScreen().frame()
            return {"width": int(screen.size.width), "height": int(screen.size.height)}
        except ImportError:
            print("AppKit is not available. Make sure you are running this on macOS.")
            return {"width": 1920, "height": 1080}

    else:  # Windows & Linux
        try:
            from screeninfo import get_monitors  # Cross-platform library
            monitor = get_monitors()[0]  # Get primary monitor
            return {"width": monitor.width, "height": monitor.height}
        except ImportError:
            print("screeninfo package not found. Install it using 'pip install screeninfo'")
            return {"width": 1920, "height": 1080}
        

def get_window_adjustments():
    """Returns recommended x, y offsets for window positioning"""
    if sys.platform == "darwin":  # macOS
        return -4, 24  # macOS has a small title bar, no border
    elif sys.platform == "win32":  # Windows
        return -8, 0  # Windows has a border on the left
    else:  # Linux (varies by window manager)
        return 0, 0  # Adjust as needed for your WM