#!/usr/bin/env python3
"""
Launch Chrome with Remote Debugging for browser-use

This script closes any existing Chrome instances and relaunches Chrome
with your profile (copied to automation directory) and remote debugging enabled.

Cross-platform: Works on macOS, Windows, and Linux
"""

import os
import platform
import shutil
import subprocess
import sys
import time
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


def close_chrome():
	"""Close existing Chrome instances (cross-platform)"""
	system = platform.system()

	try:
		if system == 'Darwin':
			subprocess.run(['pkill', '-x', 'Google Chrome'], check=False, capture_output=True)
		elif system == 'Windows':
			subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'], check=False, capture_output=True)
		else:  # Linux
			subprocess.run(['pkill', 'chrome'], check=False, capture_output=True)
			subprocess.run(['pkill', 'chromium'], check=False, capture_output=True)
	except Exception:
		pass  # Ignore errors if Chrome wasn't running


def main():
	print('🔄 Closing existing Chrome instances...')
	close_chrome()
	time.sleep(2)  # Wait for Chrome to fully shut down

	# Get Chrome paths
	chrome_exe, profile_base = get_chrome_paths()

	# Check if Chrome exists
	if not Path(chrome_exe).exists():
		print(f'❌ Chrome not found at: {chrome_exe}')
		print('   Please install Google Chrome or update the path in this script.')
		sys.exit(1)

	# Set up automation directory
	automation_dir = Path.home() / '.chrome-automation'
	source_profile = profile_base / 'Default'
	dest_profile = automation_dir / 'Default'

	# Create automation directory
	if not automation_dir.exists():
		print(f'📁 Creating automation directory: {automation_dir}')
		automation_dir.mkdir(parents=True, exist_ok=True)

	# Copy profile on first run
	if not dest_profile.exists():
		print('📋 First run detected - copying your Default profile to automation directory...')
		print('   This includes all your logged-in sessions (GitHub, Google, etc.)')
		print(f'   Source: {source_profile}')
		print(f'   Destination: {dest_profile}')

		if source_profile.exists():
			shutil.copytree(source_profile, dest_profile)
			print('✅ Profile copied successfully')
		else:
			print(f'⚠️  Default profile not found at: {source_profile}')
			print('   Creating empty profile...')
			dest_profile.mkdir(parents=True, exist_ok=True)
	else:
		print('📂 Using existing automation profile (sessions preserved from previous runs)')

	print('')
	print('🚀 Launching Chrome with remote debugging on port 9222...')
	print(f'📂 Using profile: Default (from {automation_dir})')
	print('🔗 CDP endpoint: http://localhost:9222')
	print('')
	print('⚠️  Keep this terminal window open - closing it will close Chrome')
	print('💡 In another terminal, run: uv run browser_use_shopping.py')
	print('')
	print(f'ℹ️  To reset and re-copy your profile, delete: {automation_dir}')
	print('')

	# Launch Chrome with remote debugging
	cmd = [
		chrome_exe,
		'--remote-debugging-port=9222',
		f'--user-data-dir={automation_dir}',
		'--profile-directory=Default',
	]

	try:
		subprocess.run(cmd)
	except KeyboardInterrupt:
		print('\n👋 Shutting down Chrome...')
		sys.exit(0)


if __name__ == '__main__':
	main()
