import sys


def get_screen_resolution():
	if sys.platform == 'darwin':  # macOS
		try:
			from AppKit import NSScreen

			screen = NSScreen.mainScreen().frame()
			return {'width': int(screen.size.width), 'height': int(screen.size.height)}
		except ImportError:
			print('AppKit is not available. Make sure you are running this on macOS with pyobjc installed.')
		except Exception as e:
			print(f'Error retrieving macOS screen resolution: {e}')
		return {'width': 2560, 'height': 1664}

	else:  # Windows & Linux
		try:
			from screeninfo import get_monitors

			monitors = get_monitors()
			if not monitors:
				raise Exception('No monitors detected.')
			monitor = monitors[0]
			return {'width': monitor.width, 'height': monitor.height}
		except ImportError:
			print("screeninfo package not found. Install it using 'pip install screeninfo'.")
		except Exception as e:
			print(f'Error retrieving screen resolution: {e}')

		return {'width': 1920, 'height': 1080}


def get_window_adjustments():
	"""Returns recommended x, y offsets for window positioning"""
	if sys.platform == 'darwin':  # macOS
		return -4, 24  # macOS has a small title bar, no border
	elif sys.platform == 'win32':  # Windows
		return -8, 0  # Windows has a border on the left
	else:  # Linux
		return 0, 0
