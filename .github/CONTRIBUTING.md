# Contributing to browser-use

We love contributions! Please read through these links to get started:

 - 🔢 [Contribution Guidelines](https://docs.browser-use.com/development/contribution-guide)
 - 👾 [Local Development Setup Guide](https://docs.browser-use.com/development/local-setup)
 - 🏷️ [Issues Tagged: `#help-wanted`](https://github.com/browser-use/browser-use/issues?q=is%3Aissue%20state%3Aopen%20label%3A%22help%20wanted%22)
 - 🔌 [Integration Example Guidelines](../examples/integrations/README.md)

## Running tests locally

`uv run pytest tests/ci` runs tests in one process by default. The configured
`--dist=loadscope` option controls how pytest-xdist groups tests only when workers
are enabled.

To run the CI test suite in parallel with automatic worker selection, use
`uv run pytest -n auto tests/ci` or `./bin/test.sh`. The configured `loadscope`
scheduler groups test functions by module and test methods by class to help
reuse scoped fixtures.
