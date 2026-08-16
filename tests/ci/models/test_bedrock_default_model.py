"""The Bedrock defaults must stay in step with the AWS example we ship.

They had drifted: both classes defaulted to anthropic.claude-3-5-sonnet-20240620-v1:0,
which AWS moved to Legacy on 2026-01-30 and retired on 2026-07-30, while
examples/models/aws.py had already moved on. Anyone constructing either class
without naming a model was calling a model Bedrock no longer serves.
"""

import re
from pathlib import Path

from browser_use.llm.aws.chat_anthropic import ChatAnthropicBedrock
from browser_use.llm.aws.chat_bedrock import ChatAWSBedrock

EXAMPLE = Path(__file__).parents[3] / 'examples' / 'models' / 'aws.py'


def _example_model() -> str:
	match = re.search(r"model='([^']+)'", EXAMPLE.read_text())
	assert match, f'no model= found in {EXAMPLE}'
	return match.group(1)


def test_bedrock_default_matches_the_example() -> None:
	assert ChatAWSBedrock().model == _example_model()


def test_anthropic_bedrock_default_matches_the_example() -> None:
	assert ChatAnthropicBedrock().model == _example_model()
