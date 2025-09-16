# Browser-Use Agent Guidelines

## Commands
- **Setup**: `uv venv --python 3.11 && source .venv/bin/activate && uv sync`
- **Test single**: `uv run pytest -vxs tests/ci/test_specific_file.py`
- **Test all**: `uv run pytest -vxs tests/ci`
- **Lint**: `uv run ruff check --fix && uv run ruff format`
- **Type check**: `uv run pyright`
- **Pre-commit**: `uv run pre-commit run --all-files`

## Code Style
- **Python**: >=3.11, async-first, tabs for indentation
- **Types**: Modern style (`str | None`, `list[str]`, `dict[str, Any]`)
- **Models**: Pydantic v2 with `ConfigDict(extra='forbid', validate_by_name=True, validate_by_alias=True)`
- **Imports**: Use `from uuid_extensions import uuid7str` for IDs, group standard library imports first
- **Error handling**: Use runtime assertions at function boundaries
- **Logging**: Keep console logging in `_log_*` prefixed methods
- **Testing**: Use real objects, never mock (except LLM), use pytest-httpserver for test servers
