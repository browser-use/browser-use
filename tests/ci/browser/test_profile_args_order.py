from browser_use.browser.profile import BrowserProfile, CHROME_DEFAULT_ARGS


def test_get_args_preserves_default_args_order(tmp_path):
    """Verify that ignoring default args preserves the exact order of remaining CHROME_DEFAULT_ARGS (#5397)."""
    ignored = [CHROME_DEFAULT_ARGS[0], CHROME_DEFAULT_ARGS[3]] if len(CHROME_DEFAULT_ARGS) > 3 else [CHROME_DEFAULT_ARGS[0]]
    expected_remaining = [arg for arg in CHROME_DEFAULT_ARGS if arg not in set(ignored)]

    profile = BrowserProfile(user_data_dir=str(tmp_path), enable_default_extensions=False, ignore_default_args=ignored)
    args = profile.get_args()

    default_subset = [arg for arg in args if arg in set(CHROME_DEFAULT_ARGS)]
    assert default_subset == expected_remaining


def test_get_args_ignore_default_args_true(tmp_path):
    """When ignore_default_args=True, no default args should be included."""
    profile = BrowserProfile(user_data_dir=str(tmp_path), enable_default_extensions=False, ignore_default_args=True)
    args = profile.get_args()
    assert not any(arg in set(CHROME_DEFAULT_ARGS) for arg in args)


def test_get_args_ignore_default_args_empty_or_none(tmp_path):
    """When ignore_default_args is empty, all default args should be included in exact order."""
    profile = BrowserProfile(user_data_dir=str(tmp_path), enable_default_extensions=False, ignore_default_args=[])
    args = profile.get_args()
    default_subset = [arg for arg in args if arg in set(CHROME_DEFAULT_ARGS)]
    assert default_subset == list(CHROME_DEFAULT_ARGS)
