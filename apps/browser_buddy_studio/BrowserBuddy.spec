# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

APP_DIR = Path(SPECPATH)
ICON = APP_DIR / 'assets' / 'AppIcon.icns'
VERSION = os.environ.get('APP_VERSION', '1.0.0')

datas = [(str(APP_DIR / 'frontend' / 'dist'), 'frontend/dist')]
binaries = []
hiddenimports = ['webview.platforms.cocoa']
tmp_ret = collect_all('browser_use')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]
tmp_ret = collect_all('webview')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]
tmp_ret = collect_all('safehttpx')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]
tmp_ret = collect_all('groovy')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]
tmp_ret = collect_all('uvicorn')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]
tmp_ret = collect_all('fastapi')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]


a = Analysis(
	['main.py'],
	pathex=[],
	binaries=binaries,
	datas=datas,
	hiddenimports=hiddenimports,
	hookspath=[],
	hooksconfig={},
	runtime_hooks=[],
	excludes=['browser_use.llm.oci_raw'],
	noarchive=False,
	optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
	pyz,
	a.scripts,
	[],
	exclude_binaries=True,
	name='BrowserBuddy',
	debug=False,
	bootloader_ignore_signals=False,
	strip=False,
	upx=True,
	console=False,
	disable_windowed_traceback=False,
	argv_emulation=False,
	target_arch=None,
	codesign_identity=None,
	entitlements_file=None,
)
coll = COLLECT(
	exe,
	a.binaries,
	a.datas,
	strip=False,
	upx=True,
	upx_exclude=[],
	name='BrowserBuddy',
)
app = BUNDLE(
	coll,
	name='BrowserBuddy.app',
	icon=str(ICON) if ICON.exists() else None,
	bundle_identifier='com.example.browserbuddystudio',
	info_plist={
		'CFBundleDisplayName': 'BrowserBuddy',
		'CFBundleShortVersionString': VERSION,
		'CFBundleVersion': VERSION,
		'LSMinimumSystemVersion': '12.0',
		'LSApplicationCategoryType': 'public.app-category.productivity',
		'NSHighResolutionCapable': True,
		'NSHumanReadableCopyright': 'BrowserBuddy',
	},
)
