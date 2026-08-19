from browser_use.utils import _is_newer_browser_use_version


def test_prerelease_is_newer_than_previous_stable():
	assert _is_newer_browser_use_version('0.12.9', '0.13.0rc3') is False


def test_stable_release_is_newer_than_same_release_candidate():
	assert _is_newer_browser_use_version('0.13.0', '0.13.0rc3') is True


def test_later_release_candidate_is_newer():
	assert _is_newer_browser_use_version('0.13.0rc4', '0.13.0rc3') is True
