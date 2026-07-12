"""Tests for boolean environment-variable parsing in browser_use.config.

Two bugs are pinned here:

1. `OldConfig` used `os.getenv(...).lower()[:1] in 'ty1'`. Because `'' in 'ty1'`
   is True, an empty value flipped the flag on — e.g. `SKIP_LLM_API_KEY_VERIFICATION=`
   silently skipped API-key verification. The substring test was also too loose
   (any value starting with t/y/1, such as `yesterday`, counted as True).

2. `FlatEnvConfig` (pydantic-settings) rejects `''` for a `bool` field, so a bare
   `ANONYMIZED_TELEMETRY=` in the environment made `import browser_use` raise a
   ValidationError and the whole library unimportable.
"""

from browser_use.config import FlatEnvConfig, OldConfig


def test_empty_bool_env_falls_back_to_default(monkeypatch):
	# default False -> empty stays False (previously became True)
	monkeypatch.setenv('SKIP_LLM_API_KEY_VERIFICATION', '')
	assert OldConfig().SKIP_LLM_API_KEY_VERIFICATION is False

	monkeypatch.setenv('IS_IN_EVALS', '   ')  # whitespace-only counts as empty
	assert OldConfig().IS_IN_EVALS is False

	# default True -> empty stays True (treated as "unset")
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', '')
	assert OldConfig().ANONYMIZED_TELEMETRY is True


def test_loose_values_are_not_truthy(monkeypatch):
	# Values that merely start with t/y/1 must not count as True anymore.
	for value in ('yesterday', 'trap', 'nope', 'false', '0', 'no', 'off'):
		monkeypatch.setenv('SKIP_LLM_API_KEY_VERIFICATION', value)
		assert OldConfig().SKIP_LLM_API_KEY_VERIFICATION is False, value


def test_affirmative_values_are_truthy(monkeypatch):
	for value in ('true', 'True', '1', 'yes', 'y', 'on', 't', '  TRUE  '):
		monkeypatch.setenv('SKIP_LLM_API_KEY_VERIFICATION', value)
		assert OldConfig().SKIP_LLM_API_KEY_VERIFICATION is True, value


def test_flat_env_config_does_not_crash_on_empty_bool(monkeypatch):
	# Regression: a bare `ANONYMIZED_TELEMETRY=` used to raise ValidationError here,
	# which is what broke `import browser_use`.
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', '')
	monkeypatch.setenv('BROWSER_USE_VERSION_CHECK', '  ')
	cfg = FlatEnvConfig()
	assert cfg.ANONYMIZED_TELEMETRY is True  # default applied
	assert cfg.BROWSER_USE_VERSION_CHECK is True
