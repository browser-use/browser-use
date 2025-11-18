"""Test that disable_security flag properly merges --disable-features flags without breaking extensions."""

import tempfile

from browser_use.browser.profile import BrowserProfile


class TestBrowserProfileDisableSecurity:
	"""Test disable_security flag behavior."""

	def test_disable_security_preserves_extension_features(self):
		"""Test that disable_security=True doesn't break extension features by properly merging --disable-features flags."""

		# Test with disable_security=False (baseline)
		profile_normal = BrowserProfile(disable_security=False, user_data_dir=tempfile.mkdtemp(prefix='test-normal-'))
		profile_normal.detect_display_configuration()
		args_normal = profile_normal.get_args()

		# Test with disable_security=True
		profile_security_disabled = BrowserProfile(disable_security=True, user_data_dir=tempfile.mkdtemp(prefix='test-security-'))
		profile_security_disabled.detect_display_configuration()
		args_security_disabled = profile_security_disabled.get_args()

		# Extract disable-features args
		def extract_disable_features(args):
			for arg in args:
				if arg.startswith('--disable-features='):
					return set(arg.split('=', 1)[1].split(','))
			return set()

		features_normal = extract_disable_features(args_normal)
		features_security_disabled = extract_disable_features(args_security_disabled)

		# Check that extension-related features are preserved
		extension_features = {
			'ExtensionManifestV2Disabled',
			'ExtensionDisableUnsupportedDeveloper',
			'ExtensionManifestV2Unsupported',
		}

		security_features = {'IsolateOrigins', 'site-per-process'}

		# Verify that security disabled has both extension and security features
		missing_extension_features = extension_features - features_security_disabled
		missing_security_features = security_features - features_security_disabled

		assert not missing_extension_features, (
			f'Missing extension features when disable_security=True: {missing_extension_features}'
		)
		assert not missing_security_features, f'Missing security features when disable_security=True: {missing_security_features}'

		# Verify that security disabled profile has more features than normal (due to added security features)
		assert len(features_security_disabled) > len(features_normal), (
			'Security disabled profile should have more features than normal profile'
		)

		# Verify all normal features are preserved in security disabled profile
		missing_normal_features = features_normal - features_security_disabled
		assert not missing_normal_features, f'Normal features missing from security disabled profile: {missing_normal_features}'

	def test_disable_features_flag_deduplication(self):
		"""Test that duplicate --disable-features values are properly deduplicated."""

		profile = BrowserProfile(
			disable_security=True,
			user_data_dir=tempfile.mkdtemp(prefix='test-dedup-'),
			# Add duplicate features to test deduplication
			args=['--disable-features=TestFeature1,TestFeature2', '--disable-features=TestFeature2,TestFeature3'],
		)
		profile.detect_display_configuration()
		args = profile.get_args()

		# Extract disable-features args
		disable_features_args = [arg for arg in args if arg.startswith('--disable-features=')]

		# Should only have one consolidated --disable-features flag
		assert len(disable_features_args) == 1, f'Expected 1 disable-features flag, got {len(disable_features_args)}'

		features = set(disable_features_args[0].split('=', 1)[1].split(','))

		# Should have all test features without duplicates
		expected_test_features = {'TestFeature1', 'TestFeature2', 'TestFeature3'}
		assert expected_test_features.issubset(features), f'Missing test features: {expected_test_features - features}'
