from browser_use.tools.registry.service import Registry


async def test_sensitive_data_kwarg_reaches_the_action():
	"""execute_action(sensitive_data=...) must reach actions that declare the
	parameter, not be silently dropped by signature normalization."""
	reg = Registry()
	received: dict = {}

	@reg.action(description='probe')
	async def probe(value: str, has_sensitive_data: bool = False, sensitive_data: dict | None = None):
		received['has_sensitive_data'] = has_sensitive_data
		received['sensitive_data'] = sensitive_data
		return 'ok'

	result = await reg.execute_action(
		'probe',
		{'value': 'x'},
		sensitive_data={'secret': 'hunter2'},
	)
	assert result == 'ok'
	assert received['sensitive_data'] == {'secret': 'hunter2'}
