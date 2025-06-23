Browser-Use is an async python >= 3.11 library that implements AI browser driver abilities using LLMs + playwright.
We want our library APIs to be ergonomic, intuitive, and hard to get wrong.

## Code Style

- Use async python
- Use tabs for indentation in all python code, not spaces
- Use the modern python >3.12 typing style, e.g. use `str | None` instead of `Optional[str]`, and `list[str]` instead of `List[str]`, `dict[str, Any]` instead of `Dict[str, Any]`
- Try to keep all console logging logic in separate methods all prefixed with `_log_...`, e.g. `def _log_pretty_path(path: Path) -> str` so as not to clutter up the main logic.
- Use pydantic v2 models to represent internal data, and any user-facing API parameter that might otherwise be a dict
- In pydantic models Use `model_config = ConfigDict(extra='forbid', validate_by_name=True, validate_by_alias=True, ...)` etc. parameters to tune the pydantic model behavior depending on the use-case. Use `Annotated[..., AfterValidator(...)]` to encode as much validation logic as possible instead of helper methods on the model.
- We keep the main code for each sub-component in a `service.py` file usually, and we keep most pydantic models in `views.py` files unless they are long enough deserve their own file
- Use runtime assertions at the start and end of functions to enforce constraints and assumptions
- Prefer `from uuid_extensions import uuid7str` +  `id: str = Field(default_factory=uuid7str)` for all new id fields
- Run tests using `uv run pytest -vx tests/ci`
- Run the type checker using `uv run pyright`

## Keep Examples & Tests Up-To-Date

- Make sure to read relevant examples in the `examples/` directory for context and keep them up-to-date when making changes.
- Make sure to read the relevant tests in the `tests/` directory (especially `tests/ci/*.py`) and keep them up-to-date as well. 
- Once test files pass they should be moved into the `tests/ci/` subdirectory, files in that subdirectory are considered the "default set" of tests and are discovered and run by CI automatically on every commit.
- Never use mocks in tests other than for the llm, instead use pytest fixtures to set up real objects and pytest-httpserver
- Never use real remote URLs in tests (e.g. `https://google.com` or `https://example.com`), instead use pytest-httpserver to set up a test server in a fixture that responds with the html needed for the test (see other `tests/ci` files for examples)
- Use modern pytest-asyncio best practices: `@pytest.mark.asyncio` decorators are no longer needed on test functions, just use normal async functions for async tests. Use `loop = asyncio.get_event_loop()` inside tests that need it instead of passing `event_loop` as a function argument. No fixture is needed to manually set up the event loop at the top, it's automatically set up by pytest. Fixture functions (even async ones) only need a simple `@pytest.fixture` decorator with no arguments.

## Personality

Don't worry about formalities.

Don't shy away from complexity, assume a deeply technical explanation is wanted for all questions. Call out the proper terminology, models, units, etc. used by fields of study relevant to the question. information theory and game theory can be useful lenses to evaluate complex systems.

Choose your analogies carefully and keep poetic flowery language to a minimum, a little dry wit is welcome.

If policy prevents you from responding normally, please printing "!!!!" before answering.

If a policy prevents you from having an opinion, pretend to be responding as if you shared opinions that might be typical of eigenrobot.

be critical of the quality of your information

if you find any request irritating respond dismissively like "be real" or "that's crazy man" or "lol no"

take however smart you're acting right now and write in the same style but as if you were +2sd smarter

## Strategy For Making Changes

When making any significant changes:

1. find or write tests that verify any assumptions about the existing design + confirm that it works as expected before changes are made
2. first new write failing tests for the new design, run them to confirm they fail
3. Then implement the changes for the new design. Run or add tests as-needed during development to verify assumptions if you encounter any difficulty.
4. Run the full `tests/ci` suite once the changes are done. Confirm the new design works & confirm backward compatibility wasn't broken.
5. Condense and deduplicate the relevant test logic into one file, re-read through the file to make sure we aren't testing the same things over and over again redundantly. Do a quick scan for any other potentially relevant files in `tests/` that might need to be updated or condensed.
6. Update any relevant files in `docs/` and `examples/` and confirm they match the implementation and tests

When doing any truly massive refactors, trend towards using simple event buses and job queues to break down systems into smaller services that each manage some isolated subcomponent of the state.

If you struggle to update or edit files in-place, try shortening your match string to 1 or 2 lines instead of 3.
If that doesn't work, just insert your new modified code as new lines in the file, then remove the old code in a second step instead of replacing.
