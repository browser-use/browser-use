"""
Assay evidence trail for browser-use agents.

Records Anthropic API calls made through the patched SDK path. Each call
produces one receipt: model ID, token counts, latency, and SHA-256
hashes of the input and output content.

Setup:
    pip install assay-ai
    export ANTHROPIC_API_KEY=...

Run (raw receipts only):
    python assay_audit.py
    assay verify <trace_id>          # structural check

Run (signed proof pack — tamper-evident, verifiable offline):
    assay run -- python assay_audit.py
    assay verify-pack ./proof_pack_<trace_id>/   # integrity + signature check

What each receipt contains:
    - model_id, input_tokens, output_tokens, latency_ms
    - SHA-256 hash of input and output content
    - callsite location (file:line)

What assay run adds (signed pack only):
    - SHA-256 manifest over all receipts
    - Ed25519 signature over the manifest
    - Any tampered or missing receipt fails verification
    - Pack verifiable by any party with the public key — no server access

Trust tier: T0 — locally generated signing key, no external trust anchor.
Verification confirms the pack was not modified after signing; it does not
confirm who signed it. For CI-bound signing, see T1 in the Assay docs.
"""

import asyncio

from dotenv import load_dotenv

try:
	from assay.integrations.anthropic import get_trace_id, patch  # type: ignore[import-untyped]
except ImportError:
	print('assay-ai is not installed. Run: pip install assay-ai')
	exit(1)

from browser_use import Agent
from browser_use.llm import ChatAnthropic

load_dotenv()

# Patch the Anthropic SDK before any client is created.
# Every messages.create() call now emits a receipt automatically.
patch()


async def main():
	llm = ChatAnthropic(model='claude-sonnet-4-0', temperature=0.0)
	agent = Agent(
		task='Go to github.com/browser-use/browser-use and report the current number of GitHub stars',
		llm=llm,
	)

	result = await agent.run(max_steps=10)

	trace_id = get_trace_id()
	if trace_id:
		print(f'\nReceipts logged to trace: {trace_id}')
		print(f'Verify: assay verify {trace_id}')

	return result


if __name__ == '__main__':
	asyncio.run(main())
