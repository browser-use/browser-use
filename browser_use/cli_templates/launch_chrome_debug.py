#!/usr/bin/env python3
"""
Launch Chrome with Remote Debugging for browser-use

This script launches Chrome with remote debugging enabled, using a temporary
directory that is automatically cleaned up when the script exits.

Cross-platform: Works on macOS, Windows, and Linux

Usage:
    python launch_chrome_debug.py                    # Uses Default profile
    python launch_chrome_debug.py --profile "Profile 6"  # Uses specific profile
"""

import argparse
import atexit
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


def get_chrome_paths():
	"""Get Chrome executable and profile paths based on OS"""
	system = platform.system()

	if system == 'Darwin':  # macOS
		chrome_exe = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
		profile_base = Path.home() / 'Library/Application Support/Google/Chrome'
	elif system == 'Windows':
		chrome_exe = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
		if not Path(chrome_exe).exists():
			chrome_exe = r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
		profile_base = Path(os.environ.get('LOCALAPPDATA', '')) / 'Google/Chrome/User Data'
	else:  # Linux
		chrome_exe = '/usr/bin/google-chrome'
		if not Path(chrome_exe).exists():
			chrome_exe = '/usr/bin/chromium-browser'
		profile_base = Path.home() / '.config/google-chrome'

	return chrome_exe, profile_base


def cleanup_port_9222():
	"""Kill only the process using port 9222 (previous automation Chrome)"""
	system = platform.system()

	try:
		if system == 'Darwin':  # macOS/Linux
			# Use lsof to find process using port 9222
			result = subprocess.run(['lsof', '-i', ':9222', '-t'], capture_output=True, text=True, check=False)
			if result.stdout.strip():
				pid = result.stdout.strip().split('\n')[0]  # Get first PID if multiple
				print(f'⚠️  Found previous automation session (PID {pid}), stopping it...')
				subprocess.run(['kill', pid], check=False, capture_output=True)
				import time

				time.sleep(2)  # Wait for port to be freed
				print('✅ Port 9222 is now available')
			else:
				print('✅ Port 9222 is available')
		elif system == 'Windows':
			# Use netstat to find process using port 9222
			result = subprocess.run(['netstat', '-ano', '-p', 'TCP'], capture_output=True, text=True, check=False)
			for line in result.stdout.split('\n'):
				if ':9222' in line and 'LISTENING' in line:
					pid = line.strip().split()[-1]
					print(f'⚠️  Found previous automation session (PID {pid}), stopping it...')
					subprocess.run(['taskkill', '/F', '/PID', pid], check=False, capture_output=True)
					import time

					time.sleep(2)
					print('✅ Port 9222 is now available')
					break
			else:
				print('✅ Port 9222 is available')
		else:  # Linux
			result = subprocess.run(['lsof', '-i', ':9222', '-t'], capture_output=True, text=True, check=False)
			if result.stdout.strip():
				pid = result.stdout.strip().split('\n')[0]
				print(f'⚠️  Found previous automation session (PID {pid}), stopping it...')
				subprocess.run(['kill', pid], check=False, capture_output=True)
				import time

				time.sleep(2)
				print('✅ Port 9222 is now available')
			else:
				print('✅ Port 9222 is available')
	except Exception as e:
		# If port checking fails, just continue (port is likely free)
		print(f'ℹ️  Could not check port 9222 status: {e}')
		pass


def main():
	# Parse command line arguments
	parser = argparse.ArgumentParser(
		description='Launch Chrome with remote debugging for browser-use',
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog="""
Examples:
  python launch_chrome_debug.py                    # Uses Default profile
  python launch_chrome_debug.py --profile "Profile 6"  # Uses Profile 6
		""",
	)
	parser.add_argument(
		'--profile',
		'-p',
		type=str,
		default='Default',
		help='Chrome profile name to use (default: Default)',
	)
	args = parser.parse_args()

	profile_name = args.profile

	# Check and cleanup port 9222
	print('')
	print('🔍 Checking port 9222...')
	cleanup_port_9222()
	print('')

	# Get Chrome paths
	chrome_exe, profile_base = get_chrome_paths()

	# Check if Chrome exists
	if not Path(chrome_exe).exists():
		print(f'❌ Chrome not found at: {chrome_exe}')
		print('   Please install Google Chrome or update the path in this script.')
		sys.exit(1)

	# Create temporary directory for this session
	automation_dir = Path(tempfile.mkdtemp(prefix='chrome-automation-'))
	source_profile = profile_base / profile_name
	dest_profile = automation_dir / profile_name

	# Register cleanup handlers to delete temp directory on exit
	def cleanup_temp_dir():
		"""Delete the temporary automation directory"""
		try:
			if automation_dir.exists():
				shutil.rmtree(automation_dir, ignore_errors=True)
		except Exception:
			pass

	atexit.register(cleanup_temp_dir)

	# Handle Ctrl+C gracefully
	def signal_handler(sig, frame):
		print('\n👋 Shutting down Chrome...')
		cleanup_temp_dir()
		sys.exit(0)

	signal.signal(signal.SIGINT, signal_handler)
	if hasattr(signal, 'SIGTERM'):
		signal.signal(signal.SIGTERM, signal_handler)

	# Copy profile from real Chrome profile to temp directory
	print(f'📋 Copying {profile_name} profile to temporary directory...')
	print('   This includes all your logged-in sessions (GitHub, Google, etc.)')

	if source_profile.exists():
		shutil.copytree(source_profile, dest_profile)
		print('✅ Profile ready')
	else:
		print(f'⚠️  {profile_name} profile not found at: {source_profile}')
		print('   Creating empty profile...')
		dest_profile.mkdir(parents=True, exist_ok=True)

	print('')
	print('🚀 Launching Chrome with remote debugging on port 9222...')
	print('🔗 CDP endpoint: http://localhost:9222')
	print('')
	print('⚠️  Keep this terminal open - closing it will close Chrome')
	print('💡 Open a NEW terminal and run: uv run main.py')
	print('')

	# Launch Chrome with remote debugging
	cmd = [
		chrome_exe,
		'--remote-debugging-port=9222',
		f'--user-data-dir={automation_dir}',
		f'--profile-directory={profile_name}',
	]

	try:
		subprocess.run(cmd)
	except KeyboardInterrupt:
		print('\n👋 Shutting down Chrome...')
		sys.exit(0)


if __name__ == '__main__':
	main()
