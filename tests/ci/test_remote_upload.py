import pytest

from browser_use import Browser
from browser_use.repl import Repl


@pytest.mark.parametrize('remote', [False, True])
@pytest.mark.parametrize('stem', ['x' * 190, 'é' * 60])
@pytest.mark.parametrize('count', [0, 2, 400])
async def test_many_remote_files_fit_transport(chrome, tmp_path, stem, count, remote):
	"""File bytes fit in parts; the final names/MIME list must fit the same transport too."""
	names = []
	for i in range(count):
		name = f'{i:04}-{stem}.txt'
		(tmp_path / name).write_text(str(i) if i % 3 else '')
		names.append(name)
	browser = Browser(cdp_url=chrome['http'])
	repl = Repl(tmp_path, {**await browser.start(), 'BU_REMOTE_BROWSER': '1' if remote else '0'})
	check = """(async () => {
        const files = Array.from(document.getElementById('f').files);
        const valid = await Promise.all(files.map(async (file, i) =>
            file.name === String(i).padStart(4, '0') + '-' + STEM + '.txt'
            && file.type === 'text/plain'
            && await file.text() === (i % 3 ? String(i) : '')));
        const leftovers = Object.keys(window).filter(k => k.startsWith('__buUpload')).length;
        return [files.length, valid.every(Boolean), window.inputs, window.changes, leftovers].join();
    })()""".replace('STEM', repr(stem))
	try:
		result = await repl.call(
			'exec',
			"new_tab('data:text/html,<input type=file multiple id=f>'); wait_for_load(); "
			'js("window.inputs=0; window.changes=0; f.oninput=()=>inputs++; f.onchange=()=>changes++"); '
			f"print(upload_file('#f', {names!r})); print(js({check!r}))",
			30,
		)
		assert result['error'] is None, result
		events = 0 if count == 0 and not remote else 1
		assert result['output'].strip() == f'{count}\n{count},true,{events},{events},0'
	finally:
		await repl.close()
		await browser.stop()
