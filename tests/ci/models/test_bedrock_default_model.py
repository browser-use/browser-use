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

# The model AWS retired on 2026-07-30. Neither default may fall back to it.
RETIRED_MODEL = 'anthropic.claude-3-5-sonnet-20240620-v1:0'


def _example_model(cls_name: str) -> str:
	"""Return the model the example passes to a given class constructor.

	Anchored to the class name so a reorder or edit of the other example cannot
	quietly swap which value we compare against.
	"""
	match = re.search(rf"{cls_name}\([^)]*?model='([^']+)'", EXAMPLE.read_text(), re.DOTALL)
	assert match, f'no {cls_name}(model=...) found in {EXAMPLE}'
	return match.group(1)


def test_anthropic_bedrock_default_matches_its_example() -> None:
	# The ChatAnthropicBedrock example demonstrates the shipped default directly.
	assert ChatAnthropicBedrock().model == _example_model('ChatAnthropicBedrock')


def test_bedrock_default_tracks_the_anthropic_default() -> None:
	# ChatAWSBedrock is the general client; its example deliberately overrides the
	# model to a non-Anthropic provider, so the default tracks the shared Anthropic
	# default rather than that example.
	assert ChatAWSBedrock().model == ChatAnthropicBedrock().model


def test_no_default_is_the_retired_model() -> None:
	assert ChatAWSBedrock().model != RETIRED_MODEL
	assert ChatAnthropicBedrock().model != RETIRED_MODEL
