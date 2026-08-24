"""Serve a local model over an OpenAI-compatible API, on either MLX or llama.cpp.

The eval harness only ever speaks OpenAI-compatible HTTP, so swapping the inference engine
is a launcher concern, not a harness one. Pick by platform:

  mlx       macOS + Apple silicon only. Uses Metal via unified memory. MLX does ship Linux
            wheels, but its Linux GPU backend is CUDA - inside a Linux container on a Mac
            there is neither Metal nor CUDA, so it falls back to a virtualised CPU.
  llamacpp  Portable. Prebuilt llama-server binaries exist for linux-x64/arm64 and
            macos-arm64, so no compile step. This is the one that works on CI runners.

    python eval/serve_model.py --engine mlx      --model mlx-community/Qwen3.5-4B-8bit
    python eval/serve_model.py --engine llamacpp --model unsloth/Qwen3.5-4B-GGUF:Q8_0

Then point the container at it:

    -e BU_EVAL_LLM=openai -e BU_EVAL_LLM_BASE_URL=http://host.docker.internal:8188/v1
    -e BU_EVAL_LLM_API_KEY=not-needed -e BU_EVAL_SCHEMA_IN_PROMPT=1
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

LLAMA_RELEASES = 'https://api.github.com/repos/ggml-org/llama.cpp/releases/latest'
CACHE = Path(os.getenv('BU_EVAL_ENGINE_CACHE', Path.home() / '.cache' / 'browser-use-eval' / 'engines'))


def _llama_asset_name() -> str:
	"""Release asset matching this platform. Only the plain CPU/Metal builds are used:
	the accelerated variants (cuda, rocm, sycl, vulkan) need matching drivers present."""
	system, machine = platform.system(), platform.machine().lower()
	arm = machine in ('arm64', 'aarch64')
	if system == 'Darwin':
		return 'bin-macos-arm64' if arm else 'bin-macos-x64'
	if system == 'Linux':
		return 'bin-ubuntu-arm64' if arm else 'bin-ubuntu-x64'
	raise RuntimeError(f'No prebuilt llama.cpp asset for {system}/{machine}; build from source')


def ensure_llama_server() -> Path:
	"""Return a llama-server path, downloading a prebuilt release if needed."""
	existing = shutil.which('llama-server')
	if existing:
		return Path(existing)

	cached = next(CACHE.glob('llama*/**/llama-server'), None)
	if cached:
		return cached

	want = _llama_asset_name()
	print(f'[serve] fetching prebuilt llama.cpp ({want})', flush=True)
	with urllib.request.urlopen(LLAMA_RELEASES, timeout=60) as resp:
		import json

		release = json.load(resp)
	asset = next((a for a in release.get('assets', []) if want in a['name']), None)
	if asset is None:
		raise RuntimeError(f'No asset matching {want} in llama.cpp release {release.get("tag_name")}')

	CACHE.mkdir(parents=True, exist_ok=True)
	tarball = CACHE / asset['name']
	urllib.request.urlretrieve(asset['browser_download_url'], tarball)
	dest = CACHE / asset['name'].replace('.tar.gz', '')
	with tarfile.open(tarball) as tf:
		tf.extractall(dest)
	tarball.unlink(missing_ok=True)

	binary = next(dest.glob('**/llama-server'), None)
	if binary is None:
		raise RuntimeError(f'llama-server not found inside {asset["name"]}')
	binary.chmod(0o755)
	# The server links against the shared ggml/llama libs shipped beside it.
	for lib in binary.parent.glob('*.so*'):
		lib.chmod(0o755)
	print(f'[serve] llama-server at {binary}', flush=True)
	return binary


def mlx_command(model: str, host: str, port: int, max_tokens: int, no_thinking: bool) -> list[str]:
	cmd = [
		sys.executable.replace('python', 'mlx_lm.server')
		if Path(sys.executable.replace('python', 'mlx_lm.server')).exists()
		else 'mlx_lm.server',
		'--model',
		model,
		'--host',
		host,
		'--port',
		str(port),
		'--max-tokens',
		str(max_tokens),
	]
	if no_thinking:
		# Qwen3/3.5 emit chain-of-thought into a separate `reasoning` field by default and
		# can spend the whole token budget there, returning content=None.
		cmd += ['--chat-template-args', '{"enable_thinking": false}']
	return cmd


def llamacpp_command(model: str, host: str, port: int, max_tokens: int, ctx: int, no_thinking: bool) -> list[str]:
	server = ensure_llama_server()
	cmd = [str(server), '--host', host, '--port', str(port), '-c', str(ctx), '-n', str(max_tokens)]
	# A local path is a GGUF file; anything else is treated as a HF repo[:quant] to pull.
	if Path(model).exists():
		cmd += ['-m', model]
	else:
		cmd += ['-hf', model]
	if no_thinking:
		cmd += ['--reasoning-budget', '0']
	return cmd


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument('--engine', choices=['mlx', 'llamacpp'], required=True)
	parser.add_argument('--model', required=True, help='MLX: HF repo. llama.cpp: GGUF path or HF repo[:quant]')
	parser.add_argument('--host', default='0.0.0.0')
	parser.add_argument('--port', type=int, default=8188)
	parser.add_argument('--max-tokens', type=int, default=2048)
	parser.add_argument('--ctx', type=int, default=32768, help='llama.cpp context window; browser-use prompts run 10-30k')
	parser.add_argument('--thinking', action='store_true', help='Leave built-in reasoning on (off by default)')
	parser.add_argument('--print-env', action='store_true', help='Print the container env wiring and exit')
	args = parser.parse_args()

	base_url = f'http://host.docker.internal:{args.port}/v1'
	if args.print_env:
		print(f'-e BU_EVAL_LLM=openai -e BU_EVAL_MODEL={args.model} \\')
		print(f'-e BU_EVAL_LLM_BASE_URL={base_url} \\')
		print('-e BU_EVAL_LLM_API_KEY=not-needed -e BU_EVAL_SCHEMA_IN_PROMPT=1')
		return 0

	no_thinking = not args.thinking
	if args.engine == 'mlx':
		if platform.system() != 'Darwin':
			print('[serve] WARNING: MLX has no Metal outside macOS; on Linux its GPU backend is CUDA.', file=sys.stderr)
		cmd = mlx_command(args.model, args.host, args.port, args.max_tokens, no_thinking)
	else:
		cmd = llamacpp_command(args.model, args.host, args.port, args.max_tokens, args.ctx, no_thinking)

	print(f'[serve] engine={args.engine} model={args.model}', flush=True)
	print(f'[serve] {" ".join(cmd)}', flush=True)
	print(f'[serve] container base_url: {base_url}', flush=True)
	try:
		return subprocess.call(cmd)
	except FileNotFoundError as e:
		print(f'[serve] engine binary not found: {e}', file=sys.stderr)
		return 127


if __name__ == '__main__':
	raise SystemExit(main())
