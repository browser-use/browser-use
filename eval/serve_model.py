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


def port_holder(host: str, port: int) -> str | None:
	"""Describe whatever already listens on this port, or None if it is free.

	Worth checking before launching: both engines bind late and load the model lazily, so
	a taken port surfaces as a bind traceback tangled with a half-finished model download.
	"""
	import socket

	probe_host = '127.0.0.1' if host in ('0.0.0.0', '::') else host
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		sock.settimeout(0.4)
		if sock.connect_ex((probe_host, port)) != 0:
			return None

	try:
		out = (
			subprocess.run(['lsof', '-nP', f'-iTCP:{port}', '-sTCP:LISTEN'], capture_output=True, text=True, timeout=5)
			.stdout.strip()
			.splitlines()
		)
		if len(out) > 1:
			cols = out[1].split()
			return f'{cols[0]} (pid {cols[1]})'
	except Exception:
		pass
	return 'an unknown process'


def resolve_mlx_python() -> str | None:
	"""Interpreter that can run mlx_lm, or None.

	Checked in order: explicit --python, BU_EVAL_MLX_PYTHON, the interpreter running this
	script, then any sibling venv. Guessing a path from sys.executable is not viable -
	string-substituting into it produces nonsense like /opt/homebrew/opt/mlx_lm.server@3.14.
	"""
	candidates = [os.getenv('BU_EVAL_MLX_PYTHON'), sys.executable]
	for venv in ('.venv-mlx', 'mlxenv', '.venv'):
		candidates.append(str(Path.cwd() / venv / 'bin' / 'python'))
	for cand in candidates:
		if not cand or not Path(cand).exists():
			continue
		probe = subprocess.run([cand, '-c', 'import mlx_lm'], capture_output=True)
		if probe.returncode == 0:
			return cand
	return None


def mlx_command(model: str, host: str, port: int, max_tokens: int, no_thinking: bool, python: str | None) -> list[str]:
	python = python or resolve_mlx_python()
	if python is not None:
		# `python -m mlx_lm server` is the supported form; `-m mlx_lm.server` is deprecated.
		cmd = [python, '-m', 'mlx_lm', 'server']
	elif (on_path := shutil.which('mlx_lm.server')) is not None:
		cmd = [on_path]
	else:
		raise RuntimeError(
			'mlx_lm is not installed for any interpreter I can find.\n'
			'  Install it in its own venv (it pulls a full transformers stack):\n'
			'    uv venv .venv-mlx --python 3.12 && uv pip install --python .venv-mlx/bin/python mlx-lm\n'
			'  Then re-run, or point at it explicitly:\n'
			'    python eval/serve_model.py --engine mlx --python .venv-mlx/bin/python --model ...'
		)
	cmd += ['--model', model, '--host', host, '--port', str(port), '--max-tokens', str(max_tokens)]
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
	parser.add_argument('--python', default=None, help='Interpreter that has mlx_lm (mlx engine only)')
	parser.add_argument('--print-env', action='store_true', help='Print the container env wiring and exit')
	args = parser.parse_args()

	base_url = f'http://host.docker.internal:{args.port}/v1'
	if args.print_env:
		print(f'-e BU_EVAL_LLM=openai -e BU_EVAL_MODEL={args.model} \\')
		print(f'-e BU_EVAL_LLM_BASE_URL={base_url} \\')
		print('-e BU_EVAL_LLM_API_KEY=not-needed -e BU_EVAL_SCHEMA_IN_PROMPT=1')
		return 0

	holder = port_holder(args.host, args.port)
	if holder is not None:
		print(
			f'[serve] port {args.port} is already in use by {holder}.\n'
			f'  Stop it, or pick another port with --port <n> (and update BU_EVAL_LLM_BASE_URL to match).',
			file=sys.stderr,
		)
		return 2

	no_thinking = not args.thinking
	try:
		if args.engine == 'mlx':
			if platform.system() != 'Darwin':
				print('[serve] WARNING: MLX has no Metal outside macOS; on Linux its GPU backend is CUDA.', file=sys.stderr)
			cmd = mlx_command(args.model, args.host, args.port, args.max_tokens, no_thinking, args.python)
		else:
			cmd = llamacpp_command(args.model, args.host, args.port, args.max_tokens, args.ctx, no_thinking)
	except RuntimeError as e:
		# Setup problems are the common case here; a traceback buries the fix.
		print(f'[serve] {e}', file=sys.stderr)
		return 2

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
