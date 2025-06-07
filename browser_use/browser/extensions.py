# import asyncio
# import hashlib
# import json
# import logging
# import subprocess
# import zipfile
# from pathlib import Path

# import aiohttp
# import anyio

# logger = logging.getLogger(__name__)


# def get_extension_id(unpacked_path: str | Path) -> str | None:
# 	manifest_path = Path(unpacked_path) / 'manifest.json'
# 	if not manifest_path.exists():
# 		return None

# 	# chrome uses a SHA256 hash of the unpacked extension directory path to compute a dynamic id for unpacked extensions
# 	hash_obj = hashlib.sha256()
# 	hash_obj.update(str(unpacked_path).encode('utf-8'))
# 	detected_extension_id = ''.join(chr(int(h, 16) + ord('a')) for h in hash_obj.hexdigest()[:32])
# 	return detected_extension_id


# async def install_extension(extension: dict) -> bool:
# 	manifest_path = Path(extension['unpacked_path']) / 'manifest.json'
# 	crx_path = Path(extension['crx_path'])

# 	# Download extensions using:
# 	# curl -fsSL 'https://clients2.google.com/service/update2/crx?response=redirect&prodversion=1230&acceptformat=crx3&x=id%3D${EXTENSION_ID}%26uc' > extensionname.crx
# 	# unzip -d extensionname extensionname.crx

# 	if not manifest_path.exists() and not crx_path.exists():
# 		logger.info(f'[🛠️] Downloading missing extension {extension["name"]} {extension["webstore_id"]} -> {crx_path}')

# 		# Download crx file from ext.crx_url -> ext.crx_path
# 		async with aiohttp.ClientSession() as session:
# 			async with session.get(extension['crx_url']) as response:
# 				if response.headers.get('content-length') and response.content:
# 					async with anyio.open(crx_path, 'wb') as f:
# 						await f.write(await response.read())
# 				else:
# 					logger.warning(f'[⚠️] Failed to download extension {extension["name"]} {extension["webstore_id"]}')
# 					return False

# 	# Unzip crx file from ext.crx_url -> ext.unpacked_path
# 	unpacked_path = Path(extension['unpacked_path'])
# 	unpacked_path.mkdir(parents=True, exist_ok=True)

# 	try:
# 		# Try system unzip first
# 		result = subprocess.run(['/usr/bin/unzip', str(crx_path), '-d', str(unpacked_path)], capture_output=True, text=True)
# 		stdout, stderr = result.stdout, result.stderr
# 	except Exception as err1:
# 		try:
# 			# Fallback to Python's zipfile
# 			with zipfile.ZipFile(crx_path) as zf:
# 				zf.extractall(unpacked_path)
# 			stdout, stderr = '', ''
# 		except Exception as err2:
# 			logger.error(f'[❌] Failed to install {crx_path}: could not unzip crx', exc_info=(err1, err2))
# 			return False

# 	if not manifest_path.exists():
# 		logger.error(f'[❌] Failed to install {crx_path}: could not find manifest.json in unpacked_path', stdout, stderr)
# 		return False

# 	return True


# async def load_or_install_extension(ext: dict) -> dict:
# 	if not (ext.get('webstore_id') or ext.get('unpacked_path')):
# 		raise ValueError('Extension must have either webstore_id or unpacked_path')

# 	# Set statically computable extension metadata
# 	ext['webstore_id'] = ext.get('webstore_id') or ext.get('id')
# 	ext['name'] = ext.get('name') or ext['webstore_id']
# 	ext['webstore_url'] = ext.get('webstore_url') or f'https://chromewebstore.google.com/detail/{ext["webstore_id"]}'
# 	ext['crx_url'] = (
# 		ext.get('crx_url')
# 		or f'https://clients2.google.com/service/update2/crx?response=redirect&prodversion=1230&acceptformat=crx3&x=id%3D{ext["webstore_id"]}%26uc'
# 	)
# 	ext['crx_path'] = ext.get('crx_path') or str(Path(CHROME_EXTENSIONS_DIR) / f'{ext["webstore_id"]}__{ext["name"]}.crx')
# 	ext['unpacked_path'] = ext.get('unpacked_path') or str(Path(CHROME_EXTENSIONS_DIR) / f'{ext["webstore_id"]}__{ext["name"]}')

# 	manifest_path = Path(ext['unpacked_path']) / 'manifest.json'

# 	def read_manifest():
# 		with open(manifest_path) as f:
# 			return json.load(f)

# 	def read_version():
# 		return manifest_path.exists() and read_manifest().get('version')

# 	ext['read_manifest'] = read_manifest
# 	ext['read_version'] = read_version

# 	# if extension is not installed, download and unpack it
# 	if not ext['read_version']():
# 		await install_extension(ext)

# 	# autodetect id from filesystem path (unpacked extensions dont have stable IDs)
# 	ext['id'] = get_extension_id(ext['unpacked_path'])
# 	ext['version'] = ext['read_version']()

# 	if not ext['version']:
# 		logger.warning(f'[❌] Unable to detect ID and version of installed extension {pretty_path(ext["unpacked_path"])}')
# 	else:
# 		logger.info(f'[➕] Installed extension {ext["name"]} ({ext["version"]})...'.ljust(82) + pretty_path(ext['unpacked_path']))

# 	return ext


# async def is_target_extension(target):
# 	target_type = None
# 	target_ctx = None
# 	target_url = None
# 	try:
# 		target_type = await target.type
# 		target_ctx = await target.worker() or await target.page() or None
# 		target_url = await target.url or (await target_ctx.url if target_ctx else None)
# 	except Exception as err:
# 		if 'No target with given id found' in str(err):
# 			# because this runs on initial browser startup, we sometimes race with closing the initial
# 			# new tab page. it will throw a harmless error if we try to check a target that's already closed,
# 			# ignore it and return null since that page is definitely not an extension's bg page anyway
# 			target_type = 'closed'
# 			target_ctx = None
# 			target_url = 'about:closed'
# 		else:
# 			raise err

# 	target_is_bg = target_type in ['service_worker', 'background_page']
# 	target_is_extension = target_url and target_url.startswith('chrome-extension://')
# 	extension_id = target_url.split('://')[1].split('/')[0] if target_is_extension else None
# 	manifest_version = '3' if target_type == 'service_worker' else '2'

# 	return {
# 		'target_type': target_type,
# 		'target_ctx': target_ctx,
# 		'target_url': target_url,
# 		'target_is_bg': target_is_bg,
# 		'target_is_extension': target_is_extension,
# 		'extension_id': extension_id,
# 		'manifest_version': manifest_version,
# 	}


# async def load_extension_from_target(extensions, target):
# 	extension_info = await is_target_extension(target)
# 	target_is_bg = extension_info['target_is_bg']
# 	target_is_extension = extension_info['target_is_extension']
# 	target_type = extension_info['target_type']
# 	target_ctx = extension_info['target_ctx']
# 	target_url = extension_info['target_url']
# 	extension_id = extension_info['extension_id']
# 	manifest_version = extension_info['manifest_version']

# 	if not (target_is_bg and extension_id and target_ctx):
# 		return None

# 	manifest = await target_ctx.evaluate('() => chrome.runtime.getManifest()')

# 	name = manifest.get('name')
# 	version = manifest.get('version')
# 	homepage_url = manifest.get('homepage_url')
# 	options_page = manifest.get('options_page')
# 	options_ui = manifest.get('options_ui', {})

# 	if not version or not extension_id:
# 		return None

# 	options_url = await target_ctx.evaluate(
# 		'(options_page) => chrome.runtime.getURL(options_page)',
# 		options_page or options_ui.get('page') or 'options.html',
# 	)

# 	commands = await target_ctx.evaluate("""
#         async () => {
#             return await new Promise((resolve, reject) => {
#                 if (chrome.commands)
#                     chrome.commands.getAll(resolve)
#                 else
#                     resolve({})
#             })
#         }
#     """)

# 	# logger.debug(f"[+] Found Manifest V{manifest_version} Extension: {extension_id} {name} {target_url} {len(commands)}")

# 	async def dispatch_eval(*args):
# 		return await target_ctx.evaluate(*args)

# 	async def dispatch_popup():
# 		return await target_ctx.evaluate(
# 			"() => chrome.action?.openPopup() || chrome.tabs.create({url: chrome.runtime.getURL('popup.html')})"
# 		)

# 	if manifest_version == '3':

# 		async def dispatch_action(tab=None):
# 			# https://developer.chrome.com/docs/extensions/reference/api/action#event-onClicked
# 			return await target_ctx.evaluate(
# 				"""
#                 async (tab) => {
#                     tab = tab || (await new Promise((resolve) =>
#                         chrome.tabs.query({currentWindow: true, active: true}, ([tab]) => resolve(tab))))
#                     return await chrome.action.onClicked.dispatch(tab)
#                 }
#             """,
# 				tab,
# 			)

# 		async def dispatch_message(message, options=None):
# 			# https://developer.chrome.com/docs/extensions/reference/api/runtime
# 			return await target_ctx.evaluate(
# 				"""
#                 async (extension_id, message, options) => {
#                     return await chrome.runtime.sendMessage(extension_id, message, options)
#                 }
#             """,
# 				extension_id,
# 				message,
# 				options,
# 			)

# 		async def dispatch_command(command, tab=None):
# 			# https://developer.chrome.com/docs/extensions/reference/api/commands#event-onCommand
# 			return await target_ctx.evaluate(
# 				"""
#                 async (command, tab) => {
#                     return await chrome.commands.onCommand.dispatch(command, tab)
#                 }
#             """,
# 				command,
# 				tab,
# 			)

# 	elif manifest_version == '2':

# 		async def dispatch_action(tab=None):
# 			# https://developer.chrome.com/docs/extensions/mv2/reference/browserAction#event-onClicked
# 			return await target_ctx.evaluate(
# 				"""
#                 async (tab) => {
#                     tab = tab || (await new Promise((resolve) =>
#                         chrome.tabs.query({currentWindow: true, active: true}, ([tab]) => resolve(tab))))
#                     return await chrome.browserAction.onClicked.dispatch(tab)
#                 }
#             """,
# 				tab,
# 			)

# 		async def dispatch_message(message, options=None):
# 			# https://developer.chrome.com/docs/extensions/mv2/reference/runtime#method-sendMessage
# 			return await target_ctx.evaluate(
# 				"""
#                 async (extension_id, message, options) => {
#                     return await new Promise((resolve) =>
#                         chrome.runtime.sendMessage(extension_id, message, options, resolve)
#                     )
#                 }
#             """,
# 				extension_id,
# 				message,
# 				options,
# 			)

# 		async def dispatch_command(command, tab=None):
# 			# https://developer.chrome.com/docs/extensions/mv2/reference/commands#event-onCommand
# 			return await target_ctx.evaluate(
# 				"""
#                 async (command, tab) => {
#                     return await new Promise((resolve) =>
#                         chrome.commands.onCommand.dispatch(command, tab, resolve)
#                     )
#                 }
#             """,
# 				command,
# 				tab,
# 			)

# 	existing_extension = next((ext for ext in extensions if ext.get('id') == extension_id), {})

# 	new_extension = {
# 		**existing_extension,
# 		'id': extension_id,
# 		'webstore_name': name,
# 		'target': target,
# 		'target_ctx': target_ctx,
# 		'target_type': target_type,
# 		'target_url': target_url,
# 		'manifest_version': manifest_version,
# 		'manifest': manifest,
# 		'version': version,
# 		'homepage_url': homepage_url,
# 		'options_url': options_url,
# 		'dispatch_eval': dispatch_eval,  # run some JS in the extension's service worker context
# 		'dispatch_popup': dispatch_popup,  # open the extension popup
# 		'dispatch_action': dispatch_action,  # trigger an extension menubar icon click
# 		'dispatch_message': dispatch_message,  # send a chrome runtime message in the service worker context
# 		'dispatch_command': dispatch_command,  # trigger an extension keyboard shortcut command
# 	}

# 	logger.info(f'[➕] Loaded extension {name[:32]} ({version}) {target_type}...'.ljust(82) + target_url)
# 	existing_extension.update(new_extension)

# 	return new_extension


# async def get_chrome_extensions_from_persona(CHROME_EXTENSIONS, CHROME_EXTENSIONS_DIR):
# 	logger.info('*************************************************************************')
# 	logger.info(f'[⚙️] Installing {len(CHROME_EXTENSIONS)} chrome extensions from CHROME_EXTENSIONS...')
# 	try:
# 		# read extension metadata from filesystem (installing from Chrome webstore if extension is missing)
# 		for extension in CHROME_EXTENSIONS:
# 			extension.update(await load_or_install_extension(extension))

# 		# for easier debugging, write parsed extension info to filesystem
# 		await overwrite_file(
# 			CHROME_EXTENSIONS_JSON_PATH.replace('.json', '.present.json'),
# 			CHROME_EXTENSIONS,
# 		)
# 	except Exception as err:
# 		logger.error(err)
# 	logger.info('*************************************************************************')
# 	return CHROME_EXTENSIONS


# _EXTENSIONS_CACHE = None


# async def get_chrome_extensions_from_cache(browser, extensions=None, extensions_dir=None):
# 	global _EXTENSIONS_CACHE

# 	if extensions is None:
# 		extensions = CHROME_EXTENSIONS
# 	if extensions_dir is None:
# 		extensions_dir = CHROME_EXTENSIONS_DIR

# 	if _EXTENSIONS_CACHE is None:
# 		logger.info(f'[⚙️] Loading {len(extensions)} chrome extensions from CHROME_EXTENSIONS...')

# 		# find loaded Extensions at runtime / browser launch time & connect handlers
# 		# looks at all the open targets for extension service workers / bg pages
# 		for target in await browser.targets():
# 			# mutates extensions object in-place to add metadata loaded from filesystem persona dir
# 			await load_extension_from_target(extensions, target)
# 		_EXTENSIONS_CACHE = extensions

# 		# write installed extension metadata to filesystem extensions.json for easier debugging
# 		await overwrite_file(
# 			CHROME_EXTENSIONS_JSON_PATH.replace('.json', '.loaded.json'),
# 			extensions,
# 		)
# 		await overwrite_symlink(
# 			CHROME_EXTENSIONS_JSON_PATH.replace('.json', '.loaded.json'),
# 			CHROME_EXTENSIONS_JSON_PATH,
# 		)

# 	return _EXTENSIONS_CACHE


# async def setup_2captcha_extension(browser, extensions):
# 	page = None
# 	try:
# 		# open a new tab to finish setting up the 2captcha extension manually using its extension options page
# 		page = await browser.new_page()
# 		options_url = next((ext.get('options_url') for ext in extensions if ext.get('name') == 'captcha2'), None)
# 		await page.goto(options_url)
# 		await asyncio.sleep(2.5)
# 		await page.bring_to_front()

# 		# type in the API key and click the Login button (and auto-close success modal after it pops up)
# 		await page.evaluate("""() => {
#             const elem = document.querySelector("input[name=apiKey]");
#             elem.value = "";
#         }""")
# 		await page.type('input[name=apiKey]', API_KEY_2CAPTCHA, delay=25)

# 		# toggle all the important switches to ON
# 		await page.evaluate("""() => {
#             const checkboxes = Array.from(document.querySelectorAll('input#isPluginEnabled, input[name*=enabledFor], input[name*=autoSolve]'));
#             for (const checkbox of checkboxes) {
#                 if (!checkbox.checked) checkbox.click();
#             }
#         }""")

# 		dialog_opened = False

# 		async def handle_dialog(dialog):
# 			nonlocal dialog_opened
# 			await asyncio.sleep(0.5)
# 			await dialog.accept()
# 			dialog_opened = True

# 		page.on('dialog', handle_dialog)
# 		await page.click('button#connect')
# 		await asyncio.sleep(2.5)

# 		if not dialog_opened:
# 			raise ValueError(
# 				f'2captcha extension login confirmation dialog never opened, please check its options page manually: {options_url}'
# 			)

# 		logger.info('[🔑] Configured the 2captcha extension using its options page...')
# 	except Exception as err:
# 		logger.warning(f'[❌] Failed to configure the 2captcha extension using its options page! {err}')

# 	if page:
# 		await page.close()
