from browser_use.llm.deepseek.chat import _parse_tool_call_arguments


def test_parse_tool_call_arguments_valid_json():
	assert _parse_tool_call_arguments('{"action": "click", "index": 3}') == {'action': 'click', 'index': 3}


def test_parse_tool_call_arguments_repairs_malformed_json():
	parsed = _parse_tool_call_arguments('{"action": "click" "index": 3}')

	assert parsed == {'action': 'click', 'index': 3}
