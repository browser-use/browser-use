"""Action highlights (port of Browser Use Pi src/highlight.ts) on a real headless Chrome; no provider calls."""

import pytest
from conftest import script
from PIL import Image

from browser_use import Agent, Browser
from browser_use.repl.highlight import DRAW_JS

PAGE = (
	"data:text/html,<body style='margin:0;background:white'>"
	"<button style='position:absolute;left:100px;top:100px;width:200px;height:80px'>Go</button>"
)
# Click the button, then wait (at most 3 s) for the brackets to be on the page.
CLICK = f"""
import time
new_tab({PAGE!r}); wait_for_load()
click_at_xy(200, 140)
on = lambda: js("!!document.querySelector('[data-browser-use-interaction-highlight]')")
t = time.time()
while not on() and time.time() - t < 3:
    time.sleep(0.05)
shown = on()
"""


def orange(path) -> int:
	"""Pixels of the brackets' rgb(255,127,39), with JPEG tolerance."""
	rgb = Image.open(path).convert('RGB').tobytes()
	return sum(r > 200 and 80 < g < 170 and b < 100 for r, g, b in zip(rgb[::3], rgb[1::3], rgb[2::3], strict=True))


async def run(chrome, workspace, code: str, expression: str, **options) -> str:
	model, _ = script(('python', {'code': code}), ('finish_from_repl', {'success': True, 'expression': expression}))
	r = await Agent('t', model, browser=Browser(cdp_url=chrome['http']), workspace=workspace, **options).run()
	return str(r.final_result())


@pytest.mark.parametrize('options', [{}, {'highlight_actions': False}])
async def test_a_click_draws_the_brackets_unless_highlight_actions_is_false(chrome, tmp_path, options):
	assert await run(chrome, tmp_path, CLICK, 'str(shown)', **options) == str(options == {})


async def test_screenshots_never_show_the_brackets(chrome, tmp_path):
	"""The model must see the page, not our overlay: a screenshot taken while the brackets are on screen has none."""
	code = CLICK + 'time.sleep(0.2); path = screenshot(); after = on()'
	shown, after, path = (await run(chrome, tmp_path / 'a', code, 'f"{shown} {after} {path}"')).split(' ', 2)
	assert (shown, after) == ('True', 'False')  # on screen until the capture, which removed it
	assert orange(tmp_path / 'a' / path) == 0
	# the same check finds brackets drawn by hand (highlights off, so nothing removes them)
	draw = f'({DRAW_JS}).call(document.querySelector("button")) && 0'
	code = f'import time; new_tab({PAGE!r}); wait_for_load(); js({draw!r}); time.sleep(0.2); path = screenshot()'
	path = await run(chrome, tmp_path / 'b', code, 'path', highlight_actions=False)
	assert orange(tmp_path / 'b' / path) > 100
