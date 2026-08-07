from browser_use.utils import _browser_use_version_key, _is_newer_browser_use_version


def test_prerelease_is_newer_than_previous_stable():
	assert _is_newer_browser_use_version('0.12.9', '0.13.0rc3') is False


def test_stable_release_is_newer_than_same_release_candidate():
	assert _is_newer_browser_use_version('0.13.0', '0.13.0rc3') is True


def test_later_release_candidate_is_newer():
	assert _is_newer_browser_use_version('0.13.0rc4', '0.13.0rc3') is True


def test_stable_release_is_newer_than_development_release():
	# A .devN build (e.g. installed from a git checkout) must not be treated as equal to
	# the final release — otherwise the update check silently misses the stable version.
	assert _is_newer_browser_use_version('0.13.0', '0.13.0.dev1') is True


def test_development_release_is_not_newer_than_release_candidate():
	assert _is_newer_browser_use_version('0.13.0rc1', '0.13.0.dev1') is True


def test_post_release_is_newer_than_final():
	assert _is_newer_browser_use_version('0.13.0.post1', '0.13.0') is True


def test_version_key_dev_ranks_below_alpha():
	dev_key = _browser_use_version_key('1.0.0.dev1')
	alpha_key = _browser_use_version_key('1.0.0a1')
	assert dev_key is not None and alpha_key is not None
	assert dev_key < alpha_key
