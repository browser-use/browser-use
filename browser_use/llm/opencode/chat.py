from dataclasses import dataclass, field

from browser_use.llm.openai.chat import ChatOpenAI

OPENCODE_MODELS = [
	'kimi-k2.6',
	'kimi-k2.5',
	'deepseek-v4-pro',
	'deepseek-v4-flash',
	'glm-5.1',
	'glm-5',
	'qwen3.6-plus',
	'qwen3.5-plus',
	'minimax-m2.7',
	'minimax-m2.5',
	'mimo-v2-pro',
	'mimo-v2-omni',
	'mimo-v2.5-pro',
	'mimo-v2.5',
]

OPENCODE_BASE_URL = 'https://opencode.ai/zen/go/v1'


@dataclass
class ChatOpenCode(ChatOpenAI):
	"""
	A wrapper around OpenCode Go's chat API.

	OpenCode Go exposes an OpenAI-compatible REST interface, so this class
	simply overrides the default base_url and provider name while inheriting
	all serialization and invocation logic from ChatOpenAI.

	Supported models:
	    kimi-k2.6, kimi-k2.5, deepseek-v4-pro, deepseek-v4-flash,
	    glm-5.1, glm-5, qwen3.6-plus, qwen3.5-plus, minimax-m2.7,
	    minimax-m2.5, mimo-v2-pro, mimo-v2-omni, mimo-v2.5-pro, mimo-v2.5

	Usage::

	    from browser_use.llm.opencode.chat import ChatOpenCode

	    llm = ChatOpenCode(
	        model='kimi-k2.6',
	        api_key='oc-...',  # or set OPENCODE_API_KEY env var
	    )

	Environment variables:
	    OPENCODE_API_KEY: API key for OpenCode Go
	    OPENCODE_BASE_URL: Override the default base URL (optional)
	"""

	model: str = 'kimi-k2.6'
	base_url: str = field(default=OPENCODE_BASE_URL)

	@property
	def provider(self) -> str:
		return 'opencode'
