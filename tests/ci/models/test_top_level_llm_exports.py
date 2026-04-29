import browser_use


def test_documented_llm_classes_are_exported_from_top_level() -> None:
	"""Keep top-level imports in sync with the supported-models docs."""
	for name in (
		'ChatCerebras',
		'ChatDeepSeek',
		'ChatOpenRouter',
	):
		assert name in browser_use.__all__
		assert getattr(browser_use, name).__name__ == name
