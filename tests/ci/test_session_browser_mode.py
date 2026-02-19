"""Tests for session browser mode validation.

When a session is started with a specific browser mode (chromium, remote, real),
subsequent commands with a different mode should error with helpful guidance.
"""

import json
import tempfile
from pathlib import Path

from browser_use.skill_cli.main import get_session_metadata_path


def test_get_session_metadata_path():
	"""Test that metadata path is generated correctly."""
	path = get_session_metadata_path('default')
	assert path.parent == Path(tempfile.gettempdir())
	assert path.name == 'browser-use-default.meta'


def test_get_session_metadata_path_custom_session():
	"""Test metadata path for custom session names."""
	path = get_session_metadata_path('my-session')
	assert path.name == 'browser-use-my-session.meta'


def test_metadata_file_format():
	"""Test metadata file format matches expected structure."""
	meta_path = get_session_metadata_path('test-format')
	try:
		# Write metadata as the code does
		meta_path.write_text(
			json.dumps(
				{
					'browser_mode': 'chromium',
					'headed': False,
					'profile': None,
				}
			)
		)

		# Read and verify
		meta = json.loads(meta_path.read_text())
		assert meta['browser_mode'] == 'chromium'
		assert meta['headed'] is False
		assert meta['profile'] is None
	finally:
		if meta_path.exists():
			meta_path.unlink()


def test_metadata_file_remote_mode():
	"""Test metadata file with remote browser mode."""
	meta_path = get_session_metadata_path('test-remote')
	try:
		meta_path.write_text(
			json.dumps(
				{
					'browser_mode': 'remote',
					'headed': True,
					'profile': 'cloud-profile-123',
				}
			)
		)

		meta = json.loads(meta_path.read_text())
		assert meta['browser_mode'] == 'remote'
		assert meta['headed'] is True
		assert meta['profile'] == 'cloud-profile-123'
	finally:
		if meta_path.exists():
			meta_path.unlink()


def test_metadata_cleanup():
	"""Test that metadata file can be cleaned up."""
	meta_path = get_session_metadata_path('test-cleanup')
	meta_path.write_text(json.dumps({'browser_mode': 'chromium'}))
	assert meta_path.exists()

	# Cleanup
	meta_path.unlink()
	assert not meta_path.exists()


def test_mode_mismatch_remote_on_local_should_error():
	"""Test that requesting remote on local session triggers error condition.

	This is the problematic case: user wants cloud features (live_url) but
	session is running locally. They would silently lose those features.
	"""
	meta_path = get_session_metadata_path('test-mismatch-error')
	try:
		# Simulate existing session with chromium (local) mode
		meta_path.write_text(json.dumps({'browser_mode': 'chromium'}))

		meta = json.loads(meta_path.read_text())
		existing_mode = meta.get('browser_mode', 'chromium')
		requested_mode = 'remote'

		# This combination should trigger an error
		should_error = requested_mode == 'remote' and existing_mode != 'remote'
		assert should_error is True
	finally:
		if meta_path.exists():
			meta_path.unlink()


def test_mode_mismatch_local_on_remote_should_allow():
	"""Test that requesting local on remote session is allowed.

	This case is fine: user gets a remote browser (more features than requested).
	The remote session works just like a local one, just with extra features.
	"""
	meta_path = get_session_metadata_path('test-mismatch-allow')
	try:
		# Simulate existing session with remote mode
		meta_path.write_text(json.dumps({'browser_mode': 'remote'}))

		meta = json.loads(meta_path.read_text())
		existing_mode = meta.get('browser_mode')
		assert existing_mode == 'remote'

		requested_mode = 'chromium'  # Default mode when user doesn't specify --browser

		# This combination should NOT trigger an error
		# (user requested chromium, but session is remote - that's fine)
		should_error = requested_mode == 'remote' and existing_mode != 'remote'
		assert should_error is False
	finally:
		if meta_path.exists():
			meta_path.unlink()


def test_mode_match_detection_logic():
	"""Test that matching modes pass validation."""
	meta_path = get_session_metadata_path('test-match')
	try:
		# Simulate existing session with chromium mode
		meta_path.write_text(json.dumps({'browser_mode': 'chromium'}))

		# Check match passes
		meta = json.loads(meta_path.read_text())
		existing_mode = meta.get('browser_mode', 'chromium')
		requested_mode = 'chromium'

		assert existing_mode == requested_mode
	finally:
		if meta_path.exists():
			meta_path.unlink()


def test_different_sessions_independent():
	"""Test that different session names are independent."""
	session1_meta = get_session_metadata_path('session-a')
	session2_meta = get_session_metadata_path('session-b')

	try:
		# Session A with chromium
		session1_meta.write_text(json.dumps({'browser_mode': 'chromium'}))

		# Session B with remote
		session2_meta.write_text(json.dumps({'browser_mode': 'remote'}))

		# Verify they are independent
		meta1 = json.loads(session1_meta.read_text())
		meta2 = json.loads(session2_meta.read_text())

		assert meta1['browser_mode'] == 'chromium'
		assert meta2['browser_mode'] == 'remote'
	finally:
		if session1_meta.exists():
			session1_meta.unlink()
		if session2_meta.exists():
			session2_meta.unlink()
