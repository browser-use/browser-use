"""Image smoke test (docker.yml): one Agent run on the image's own Chromium with a scripted model.

No provider, no cloud browser, no network: the model is a FunctionModel that opens a data: page,
reads its title in the REPL and finishes with it. Exits non-zero unless the run completes with that title.
"""

import asyncio
import sys
import tempfile

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from browser_use import Agent, Browser

TURNS = [
	('python', {'code': "new_tab('data:text/html,<title>docker smoke</title>'); wait_for_load(); t = page_info()['title']"}),
	('finish_from_repl', {'success': True, 'expression': 't'}),
]


def scripted(messages, info):
	turn = sum(1 for m in messages if m.kind == 'response')
	return ModelResponse(parts=[ToolCallPart(*TURNS[turn])])


async def main() -> int:
	browser = Browser('chromium', headless=True)  # finds the image's /usr/bin/chromium, as a user's script would
	result = await Agent('Read the page title', FunctionModel(scripted), browser=browser, workspace=tempfile.mkdtemp()).run()
	print(f'status={result.status} result={result.final_result()!r}')
	return 0 if result.status == 'completed' and result.final_result() == 'docker smoke' else 1


if __name__ == '__main__':
	sys.exit(asyncio.run(main()))
