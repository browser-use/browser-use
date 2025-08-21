"""Test full circle: download a file and then upload it back, verifying hash matches"""

import asyncio
import hashlib
import tempfile
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionModel
from browser_use.browser import BrowserSession
from browser_use.browser.events import BrowserStateRequestEvent, FileDownloadedEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.controller.service import Controller
from browser_use.controller.views import ClickElementAction, GoToUrlAction, UploadFileAction
from browser_use.filesystem.file_system import FileSystem


@pytest.fixture(scope='function')
def download_upload_server():
	"""Create a test HTTP server with download and upload endpoints."""
	server = HTTPServer()
	server.start()

	# Test file content and hash
	test_content = b'This is a test file for download-upload verification. Random: 12345'
	test_hash = hashlib.sha256(test_content).hexdigest()

	# Store uploaded files data
	uploaded_files = []

	# Add download endpoint
	server.expect_request('/download/test-file.txt').respond_with_data(
		test_content, content_type='text/plain', headers={'Content-Disposition': 'attachment; filename="test-file.txt"'}
	)

	# Add upload page
	upload_page_html = """
	<!DOCTYPE html>
	<html>
	<head>
		<title>Upload Test Page</title>
	</head>
	<body>
		<h1>File Upload Test</h1>
		<form id="uploadForm" action="/upload" method="POST" enctype="multipart/form-data">
			<input type="file" id="fileInput" name="file" />
			<button type="submit" id="submitButton">Upload File</button>
		</form>
		<div id="result"></div>
		
		<script>
			document.getElementById('uploadForm').addEventListener('submit', async (e) => {
				e.preventDefault();
				const formData = new FormData(e.target);
				const file = formData.get('file');
				
				if (file) {
					// Read file content
					const content = await file.text();
					
					// Calculate SHA256 hash
					const encoder = new TextEncoder();
					const data = encoder.encode(content);
					const hashBuffer = await crypto.subtle.digest('SHA-256', data);
					const hashArray = Array.from(new Uint8Array(hashBuffer));
					const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
					
					// Display result
					document.getElementById('result').innerHTML = `
						<p>File uploaded successfully!</p>
						<p>Filename: <span id="uploadedFileName">${file.name}</span></p>
						<p>Size: <span id="uploadedFileSize">${file.size}</span> bytes</p>
						<p>SHA256: <span id="uploadedFileHash">${hashHex}</span></p>
					`;
					
					// Send to server for verification
					fetch('/upload', {
						method: 'POST',
						body: formData
					});
				}
			});
		</script>
	</body>
	</html>
	"""

	server.expect_request('/upload-page').respond_with_data(upload_page_html, content_type='text/html')

	# Handle upload POST request (for server-side verification)
	def handle_upload(request):
		# Store uploaded file info for verification
		if request.files and 'file' in request.files:
			file_data = request.files['file'][0]
			uploaded_files.append(
				{
					'filename': file_data['filename'],
					'content': file_data['body'],
					'hash': hashlib.sha256(file_data['body']).hexdigest(),
				}
			)
		return request.make_response({'status': 'ok'})

	server.expect_request('/upload', method='POST').respond_with_handler(handle_upload)

	# Add download page with link
	download_page_html = f"""
	<!DOCTYPE html>
	<html>
	<head>
		<title>Download Test Page</title>
	</head>
	<body>
		<h1>File Download Test</h1>
		<a id="downloadLink" href="/download/test-file.txt">Download Test File</a>
		<p>Original file SHA256: <span id="originalHash">{test_hash}</span></p>
	</body>
	</html>
	"""

	server.expect_request('/download-page').respond_with_data(download_page_html, content_type='text/html')

	server.test_hash = test_hash
	server.uploaded_files = uploaded_files

	yield server
	server.stop()


class TestDownloadUploadFullCircle:
	"""Test full circle: download a file and then upload it back"""

	async def test_download_then_upload_with_hash_verification(self, download_upload_server):
		"""Download a file, then upload it to another page, verify hash matches"""

		# Create temporary directory for downloads
		with tempfile.TemporaryDirectory() as tmpdir:
			downloads_path = Path(tmpdir) / 'downloads'
			downloads_path.mkdir()

			# Create browser session with downloads enabled
			browser_session = BrowserSession(
				browser_profile=BrowserProfile(
					headless=True,
					downloads_path=str(downloads_path),
					user_data_dir=None,
				)
			)

			await browser_session.start()

			# Create controller and file system
			controller = Controller()
			file_system = FileSystem(base_dir=tmpdir)

			try:
				base_url = f'http://{download_upload_server.host}:{download_upload_server.port}'

				# Step 1: Navigate to download page
				class GoToUrlActionModel(ActionModel):
					go_to_url: GoToUrlAction | None = None

				result = await controller.act(
					GoToUrlActionModel(go_to_url=GoToUrlAction(url=f'{base_url}/download-page', new_tab=False)), browser_session
				)
				assert result.error is None, f'Navigation to download page failed: {result.error}'

				await asyncio.sleep(0.5)

				# Get browser state to find download link
				event = browser_session.event_bus.dispatch(BrowserStateRequestEvent())
				state_result = await event.event_result()

				# Find download link
				download_link_index = None
				for idx, element in state_result.dom_state.selector_map.items():
					if element.attributes and element.attributes.get('id') == 'downloadLink':
						download_link_index = idx
						break

				assert download_link_index is not None, 'Download link not found'

				# Step 2: Click download link and wait for download
				class ClickActionModel(ActionModel):
					click_element_by_index: ClickElementAction | None = None

				# Click the download link
				result = await controller.act(
					ClickActionModel(click_element_by_index=ClickElementAction(index=download_link_index)), browser_session
				)
				assert result.error is None, f'Click on download link failed: {result.error}'

				# Wait for the download event
				try:
					download_event = await browser_session.event_bus.expect(FileDownloadedEvent, timeout=10.0)
					downloaded_file_path = download_event.path
				except TimeoutError:
					pytest.fail('Download did not complete within timeout')

				assert downloaded_file_path is not None, 'Downloaded file path is None'
				assert Path(downloaded_file_path).exists(), f'Downloaded file does not exist: {downloaded_file_path}'

				# Verify download is tracked by browser_session
				assert downloaded_file_path in browser_session.downloaded_files, (
					f'Downloaded file not tracked by browser_session: {downloaded_file_path}'
				)

				# Calculate hash of downloaded file
				downloaded_content = Path(downloaded_file_path).read_bytes()
				downloaded_hash = hashlib.sha256(downloaded_content).hexdigest()

				print(f'✅ File downloaded: {downloaded_file_path}')
				print(f'   Original hash: {download_upload_server.test_hash}')
				print(f'   Downloaded hash: {downloaded_hash}')
				assert downloaded_hash == download_upload_server.test_hash, "Downloaded file hash doesn't match original"

				# Step 3: Navigate to upload page in a new tab
				print(f'\n🔄 Opening upload page in new tab: {base_url}/upload-page')

				# Debug: Check how many tabs we have before navigation
				tabs_before = await browser_session.get_tabs()
				print(f'📑 Tabs before navigation: {len(tabs_before)} tabs')
				for i, tab in enumerate(tabs_before):
					print(f'  Tab {i}: {tab.url}')
				result = await controller.act(
					GoToUrlActionModel(go_to_url=GoToUrlAction(url=f'{base_url}/upload-page', new_tab=True)), browser_session
				)
				assert result.error is None, f'Navigation to upload page failed: {result.error}'
				print(f'✅ Navigation result: {result.extracted_content}')

				# The new tab should be automatically focused after opening
				await asyncio.sleep(2.0)  # Give more time for the new tab to load and focus

				# Debug: Get all tabs
				tabs = await browser_session.get_tabs()
				print('\n📑 All tabs after opening upload page:')
				for i, tab in enumerate(tabs):
					print(f'  Tab {i}: {tab.url} - {tab.title}')

				# Get browser state to find file input
				event = browser_session.event_bus.dispatch(BrowserStateRequestEvent())
				state_result = await event.event_result()

				# Debug: print page URL and title
				print('\n🔍 Getting DOM state:')
				print(f'  Current page URL: {state_result.url}')
				print(f'  Current page title: {state_result.title}')

				# Find file input
				file_input_index = None
				input_elements = []
				for idx, element in state_result.dom_state.selector_map.items():
					if element.tag_name and element.tag_name.lower() == 'input':
						input_elements.append((idx, element.attributes))
						if element.attributes and element.attributes.get('type') == 'file':
							file_input_index = idx
							break

				print(f'Found {len(input_elements)} input elements: {input_elements}')
				assert file_input_index is not None, 'File input not found'

				# Step 4: Upload the downloaded file
				class UploadActionModel(ActionModel):
					upload_file_to_element: UploadFileAction | None = None

				# The downloaded file should be automatically available for upload
				result = await controller.act(
					UploadActionModel(upload_file_to_element=UploadFileAction(index=file_input_index, path=downloaded_file_path)),
					browser_session,
					available_file_paths=[],  # Empty, but file is in downloaded_files
					file_system=file_system,
				)
				assert result.error is None, f'File upload failed: {result.error}'

				# Step 4b: Click the submit button to trigger the form submission
				# Get browser state to find submit button
				event = browser_session.event_bus.dispatch(BrowserStateRequestEvent())
				state_result = await event.event_result()

				# Find submit button
				submit_button_index = None
				for idx, element in state_result.dom_state.selector_map.items():
					if (
						element.tag_name
						and element.tag_name.lower() == 'button'
						and element.attributes
						and element.attributes.get('id') == 'submitButton'
					):
						submit_button_index = idx
						break

				assert submit_button_index is not None, 'Submit button not found'

				# Click the submit button
				result = await controller.act(
					ClickActionModel(click_element_by_index=ClickElementAction(index=submit_button_index)), browser_session
				)
				assert result.error is None, f'Click on submit button failed: {result.error}'

				# Wait for JavaScript to process the upload
				await asyncio.sleep(1.0)

				# Step 5: Verify upload via JavaScript (client-side hash)
				cdp_session = await browser_session.get_or_create_cdp_session()

				# Get uploaded file details from the page
				upload_verification = await browser_session.cdp_client.send.Runtime.evaluate(
					params={
						'expression': """
							(() => {
								const fileName = document.getElementById('uploadedFileName')?.textContent;
								const fileSize = document.getElementById('uploadedFileSize')?.textContent;
								const fileHash = document.getElementById('uploadedFileHash')?.textContent;
								
								return {
									fileName: fileName || null,
									fileSize: fileSize || null,
									fileHash: fileHash || null,
									hasResult: !!document.getElementById('result').textContent.includes('successfully')
								};
							})()
						""",
						'returnByValue': True,
					},
					session_id=cdp_session.session_id,
				)

				upload_info = upload_verification.get('result', {}).get('value', {})

				# Verify upload was successful
				assert upload_info.get('hasResult') is True, 'Upload result not displayed'
				assert upload_info.get('fileName') == 'test-file.txt', (
					f'Uploaded filename mismatch: {upload_info.get("fileName")}'
				)
				assert upload_info.get('fileHash') == download_upload_server.test_hash, (
					f'Uploaded file hash mismatch. Expected: {download_upload_server.test_hash}, Got: {upload_info.get("fileHash")}'
				)

				print('✅ File uploaded successfully!')
				print(f'   Uploaded filename: {upload_info.get("fileName")}')
				print(f'   Uploaded hash: {upload_info.get("fileHash")}')
				print(f'   Hash matches original: {upload_info.get("fileHash") == download_upload_server.test_hash}')

				# Step 6: Verify server-side upload (if needed)
				if download_upload_server.uploaded_files:
					server_file = download_upload_server.uploaded_files[0]
					assert server_file['hash'] == download_upload_server.test_hash, (
						f'Server-side hash mismatch. Expected: {download_upload_server.test_hash}, Got: {server_file["hash"]}'
					)
					print('✅ Server-side verification passed!')

				print('\n🎉 Full circle test passed: Download → Upload with hash verification!')

			finally:
				await browser_session.stop()
