import pytest

from browser_use.llm.google.chat import ChatGoogle


@pytest.mark.parametrize('invalid', [0, -1])
def test_chat_google_max_retries_invalid_raises(invalid):
	with pytest.raises(ValueError, match='max_retries must be at least 1'):
		ChatGoogle(model='gemini-flash-latest', max_retries=invalid)


def test_chat_google_max_retries_one_ok():
	ChatGoogle(model='gemini-flash-latest', max_retries=1)
