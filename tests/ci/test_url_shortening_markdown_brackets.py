"""Tests for wrapper-bracket handling in agent URL shortening.

A markdown link `[label](url)` lets the link's closing `)` into
URL_PATTERN matches. Before the fix, `replace_url` shortened the match
including that `)`: the closing paren vanished from the message text
(leaving the LLM an unclosed markdown link) and the hash was computed
over a URL that never existed. URLs that open the bracket themselves
(wiki/Python_(programming_language)) must keep it.
"""

from types import SimpleNamespace

from browser_use.agent.service import Agent
from browser_use.utils import split_trailing_wrapper_brackets


def run_replace(text: str, limit: int = 25) -> tuple[str, dict[str, str]]:
	"""Call the unbound method with a bare self carrying only the limit."""
	fake_self = SimpleNamespace(_url_shortening_limit=limit)
	return Agent._replace_urls_in_text(fake_self, text)  # type: ignore[arg-type]


def test_markdown_link_keeps_closing_paren():
	long_query = 'q=' + 'c' * 40
	text = f'see [docs](https://docs.example.com/search?{long_query} for info'

	# Simulate what URL_PATTERN actually captures inside a markdown link:
	# everything up to the closing paren.
	match_text = f'https://docs.example.com/search?{long_query})'
	replaced, mapping = run_replace(f'see [docs]({match_text} for info')

	assert ')' in replaced, 'the markdown link closing paren must survive shortening'
	assert replaced.count(')') == 1
	originals = list(mapping.values())
	assert originals and all(not original.endswith(')') for original in originals), (
		f'the recorded original URL must not include the markdown paren: {originals!r}'
	)


def test_url_with_own_balanced_bracket_keeps_it():
	# The URL opens '(' itself: wiki-style path with a long query
	match_text = 'https://en.wikipedia.org/wiki/Python_(programming_language)?ref=' + 'x' * 40 + ')'
	url, tail = split_trailing_wrapper_brackets(match_text)

	assert tail == ')', 'the URL opened its own bracket, so the trailing ) is part of it... '
	assert url.endswith(')') or url == match_text[:-1]


def test_prose_paren_wrapper_is_stripped():
	long_query = 'x=' + 'b' * 40
	replaced, mapping = run_replace(f'(see https://other.com/p?{long_query})')

	assert replaced.endswith(')'), 'the prose closing paren must be re-appended'
	assert len(mapping) == 1
	original = next(iter(mapping.values()))
	assert not original.endswith(')'), f'original URL must exclude the prose paren: {original!r}'


def test_short_urls_pass_through_untouched():
	replaced, mapping = run_replace('see [docs](https://docs.example.com/search?q=abc)')

	assert replaced == 'see [docs](https://docs.example.com/search?q=abc)'
	assert mapping == {}


def test_shortening_is_idempotent():
	long_query = 'q=' + 'c' * 40
	text = f'see [docs](https://docs.example.com/search?{long_query}) for info'

	once, mapping = run_replace(text)
	twice, mapping2 = run_replace(once)

	assert once == twice, 'already-shortened URLs must not be rewritten again'
	assert mapping2 == {}, f'second pass must record no new mappings: {mapping2!r}'
