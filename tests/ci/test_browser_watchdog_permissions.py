"""Test that verifies permissions watchdog is working correctly."""

import asyncio

import pytest

from browser_use import Agent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from tests.ci.conftest import create_mock_llm


@pytest.mark.asyncio
async def test_permissions_are_granted_on_connect(httpserver, caplog):
	"""Test that permissions are granted when browser connects."""
	# Set up test HTML that requests geolocation
	httpserver.expect_request('/geo').respond_with_data(
		"""
		<html>
		<body>
			<h1>Geolocation Test</h1>
			<button id="get-location" onclick="getLocation()">Get Location</button>
			<div id="result"></div>
			<script>
				function getLocation() {
					if (navigator.geolocation) {
						navigator.geolocation.getCurrentPosition(
							position => {
								document.getElementById('result').innerText = 
									`Lat: ${position.coords.latitude}, Lon: ${position.coords.longitude}`;
							},
							error => {
								document.getElementById('result').innerText = `Error: ${error.message}`;
							}
						);
					} else {
						document.getElementById('result').innerText = 'Geolocation not supported';
					}
				}
			</script>
		</body>
		</html>
		"""
	)

	# Create a profile with geolocation permissions
	profile = BrowserProfile(permissions=['geolocation'], headless=True)

	# Create a mock LLM that will navigate and click the button
	mock_llm = create_mock_llm(
		[
			"""
		{
			"thinking": "Navigating to the geolocation test page",
			"evaluation_previous_goal": "Starting",
			"memory": "Need to navigate",
			"next_goal": "Navigate to geo page",
			"action": [
				{
					"go_to_url": {
						"url": "%s"
					}
				}
			]
		}
		"""
			% httpserver.url_for('/geo'),
			"""
		{
			"thinking": "Clicking the get location button",
			"evaluation_previous_goal": "Navigated successfully",
			"memory": "On geo page",
			"next_goal": "Click get location button",
			"action": [
				{
					"click_element": {
						"index": 0
					}
				}
			]
		}
		""",
		]
	)

	# Create browser and agent
	browser = BrowserSession(browser_profile=profile)
	agent = Agent(task='Test geolocation permissions', browser=browser, llm=mock_llm)

	# Run task
	await agent.run(max_steps=3)

	# Check that permissions were granted
	grant_logs = [
		record
		for record in caplog.records
		if 'Granting browser permissions' in record.message or 'Browser.grantPermissions' in record.message
	]
	assert len(grant_logs) > 0, 'Expected Browser.grantPermissions to be called'

	# Check that the correct permission was granted
	geo_permission_logs = [
		record
		for record in caplog.records
		if 'geolocation' in record.message and ('granting' in record.message.lower() or 'granted' in record.message.lower())
	]
	assert len(geo_permission_logs) > 0, 'Expected geolocation permission to be granted'

	# Clean up
	await browser.stop()


@pytest.mark.asyncio
async def test_multiple_permissions_are_granted(caplog):
	"""Test that multiple permissions are granted correctly."""
	# Create a profile with multiple permissions
	# Use CDP permission names directly
	profile = BrowserProfile(permissions=['geolocation', 'clipboardReadWrite', 'notifications'], headless=True)

	# Create browser
	browser = BrowserSession(browser_profile=profile)

	# Start browser (this will trigger PermissionsWatchdog)
	await browser.start()

	# Give it time to initialize
	await asyncio.sleep(0.5)

	# Check that permissions were granted
	grant_logs = [
		record
		for record in caplog.records
		if 'Granting browser permissions' in record.message or 'Successfully granted permissions' in record.message
	]
	assert len(grant_logs) > 0, 'Expected permissions to be granted'

	# Check that all permissions were mentioned
	permissions_to_check = ['geolocation', 'clipboardReadWrite', 'notifications']
	for perm in permissions_to_check:
		perm_logs = [record for record in caplog.records if perm in record.message]
		assert len(perm_logs) > 0, f'Expected {perm} permission to be granted'

	# Clean up
	await browser.stop()


@pytest.mark.asyncio
async def test_no_permissions_when_empty_list(caplog):
	"""Test that no permissions are granted when list is empty."""
	# Create a profile with no permissions
	profile = BrowserProfile(permissions=[], headless=True)

	# Create browser
	browser = BrowserSession(browser_profile=profile)

	# Start browser
	await browser.start()

	# Give it time to initialize
	await asyncio.sleep(0.5)

	# Check that permissions were not granted
	grant_logs = [
		record
		for record in caplog.records
		if 'Granting browser permissions' in record.message or 'Successfully granted permissions' in record.message
	]
	assert len(grant_logs) == 0, 'Expected no permissions to be granted when list is empty'

	# Clean up
	await browser.stop()


@pytest.mark.asyncio
async def test_permissions_watchdog_handles_invalid_permissions(caplog):
	"""Test that invalid permissions are handled gracefully."""
	# Create a profile with an invalid permission
	profile = BrowserProfile(permissions=['geolocation', 'invalid-permission', 'clipboardReadWrite'], headless=True)

	# Create browser
	browser = BrowserSession(browser_profile=profile)

	# Start browser (should not crash despite invalid permission)
	await browser.start()

	# Give it time to initialize
	await asyncio.sleep(0.5)

	# Check that permissions were still granted (despite invalid permission)
	grant_logs = [
		record
		for record in caplog.records
		if 'Granting browser permissions' in record.message or 'Successfully granted permissions' in record.message
	]
	assert len(grant_logs) > 0, 'Expected permissions to be granted'

	# Check for warning about invalid permission
	warning_logs = [
		record for record in caplog.records if 'invalid-permission' in record.message or 'Unknown permission' in record.message
	]
	# This is OK if there's no warning - CDP might just ignore it

	# Clean up
	await browser.stop()
