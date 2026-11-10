"""Links in what browser-use prints: a terminal makes every character up to the next space part of the link, so a
period, comma or parenthesis right after a URL breaks it ("...MIGRATING.md." opens a 404)."""

import ast
import io
import re
import urllib.error
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / 'browser_use'
URL = re.compile(r'https?://[^\s\'"`]+')  # a quote ends it: example code such as Browser(cdp_url='https://...')
URL_NAME = re.compile(r'(^|_)URL$')


def _docstrings(tree: ast.AST) -> set[int]:
	nodes = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
	return {
		id(n.body[0].value)
		for n in ast.walk(tree)
		if isinstance(n, nodes) and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)
	}


def _is_url_name(node: ast.AST) -> bool:
	return isinstance(node, ast.FormattedValue) and isinstance(node.value, ast.Name) and bool(URL_NAME.search(node.value.id))


def _ends_with_url(node: ast.AST) -> bool:
	if isinstance(node, ast.Constant) and isinstance(node.value, str):
		return bool(re.search(r'https?://[^\s\'"`]+$', node.value))
	if isinstance(node, ast.JoinedStr) and node.values:
		last = node.values[-1]
		return _is_url_name(last) or _ends_with_url(last)
	return False


def _glued_links() -> list[str]:
	found = []
	for path in sorted(PACKAGE.rglob('*.py')):
		tree = ast.parse(path.read_text(encoding='utf-8'))
		docs = _docstrings(tree)
		where = lambda node: f'{path.relative_to(PACKAGE.parent)}:{node.lineno}'  # noqa: E731
		for node in ast.walk(tree):
			if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
				for m in URL.finditer(node.value):
					if re.search(r'[.,;:!?)\]}>]$', m.group()):
						found.append(f'{where(node)} glued: {m.group()!r}')
			elif isinstance(node, ast.JoinedStr):
				for part, after in zip(node.values, node.values[1:]):
					text = after.value if isinstance(after, ast.Constant) and isinstance(after.value, str) else ''
					if _is_url_name(part) and text[:1] and not text[:1].isspace():
						found.append(f'{where(node)} glued: {{{part.value.id}}}{text[:3]}')  # type: ignore[union-attr]
			# A raised or returned message that ends with a link gets wrapped: "(... could not start: <message>)".
			if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
				if _ends_with_url(node.exc.args[-1]):
					found.append(f'{where(node)} raised message ends with a link')
			if isinstance(node, ast.Return) and node.value is not None and _ends_with_url(node.value):
				found.append(f'{where(node)} returned message ends with a link')
	return found


def test_no_message_glues_a_character_to_a_link():
	assert _glued_links() == []


def _cloud_error(monkeypatch, status: int, detail: bytes) -> str:
	from browser_use.browser import browser as browser_mod

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'bu_' + 'x' * 40)

	def fail(req, timeout=None):
		raise urllib.error.HTTPError(req.full_url, status, 'x', {}, io.BytesIO(detail))  # type: ignore[arg-type]

	monkeypatch.setattr(browser_mod, 'urlopen_keyed', fail)
	with pytest.raises(RuntimeError) as raised:
		browser_mod._cloud('/browsers', 'POST', {})
	return str(raised.value)


def test_a_cloud_error_that_ends_with_a_link_keeps_the_link_whole(monkeypatch):
	message = _cloud_error(monkeypatch, 402, b'{"detail": "Out of credits, top up at https://cloud.browser-use.com/billing."}')
	assert 'https://cloud.browser-use.com/billing.' not in message
	assert re.search(r'https://cloud\.browser-use\.com/billing(\s|$)', message), message
	message = _cloud_error(monkeypatch, 401, b'{"detail": "Bad key"}')
	assert re.search(r'https://cloud\.browser-use\.com/settings\?tab=api-keys\s', message), message  # the hint's link too


def test_the_harness_cloud_start_error_keeps_a_trailing_link_whole(monkeypatch):
	from browser_harness import admin

	from browser_use import harness_cloud

	def refuse(*args, **kwargs):
		raise urllib.error.HTTPError('u', 402, 'x', {}, io.BytesIO(b'Top up at https://cloud.browser-use.com/billing.'))  # type: ignore[arg-type]

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'bu_' + 'x' * 40)
	monkeypatch.setattr(admin, 'start_remote_daemon', refuse)
	monkeypatch.setattr(admin, 'daemon_alive', lambda name=None: False, raising=False)
	with pytest.raises(harness_cloud.CloudBrowserError) as raised:
		harness_cloud.start('linktest', None, {}, None)
	assert re.search(r'https://cloud\.browser-use\.com/billing(\s|$)', str(raised.value)), str(raised.value)
