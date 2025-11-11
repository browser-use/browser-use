# Contributing to browser-use

Thank you for your interest in contributing to browser-use! This guide will help you get started with contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Code Style](#code-style)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Review Process](#review-process)

---

## Code of Conduct

We are committed to providing a welcoming and inclusive environment. Please be respectful and professional in all interactions.

---

## Getting Started

### Prerequisites

- Python >= 3.11
- Git
- A GitHub account

### Finding Something to Work On

1. **Check open issues**: Look for issues labeled `good first issue` or `help wanted`
2. **Review the roadmap**: See [README.md](README.md#roadmap) for planned features
3. **Propose new features**: Open an issue for discussion before starting major work

---

## Development Setup

### 1. Fork and Clone

```bash
# Fork the repository on GitHub
# Then clone your fork
git clone https://github.com/YOUR_USERNAME/browser-use.git
cd browser-use
```

### 2. Create a Virtual Environment

```bash
# Using venv
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Or using conda
conda create -n browser-use python=3.11
conda activate browser-use
```

### 3. Install Dependencies

```bash
# Install the package in development mode
pip install -e ".[dev]"

# Install Playwright browsers
playwright install chromium
```

### 4. Set Up Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
```

This will automatically run linting and formatting checks before each commit.

### 5. Verify Installation

```bash
# Run tests to verify everything works
pytest

# Run a simple example
python examples/simple.py
```

---

## Making Changes

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

Branch naming conventions:
- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation changes
- `refactor/` - Code refactoring
- `test/` - Test improvements

### 2. Make Your Changes

Follow these guidelines:
- **Small commits**: Make focused, atomic commits
- **Clear messages**: Write descriptive commit messages
- **Test as you go**: Add tests for new functionality
- **Update docs**: Update documentation for user-facing changes

### 3. Keep Your Branch Updated

```bash
git fetch upstream
git rebase upstream/main
```

---

## Code Style

We use several tools to maintain code quality:

### Ruff (Linting and Formatting)

```bash
# Check for issues
ruff check .

# Auto-fix issues
ruff check --fix .

# Format code
ruff format .
```

Our configuration:
- Line length: 130 characters
- Quote style: Single quotes
- Indentation: Tabs

### Type Hints

- Use type hints for all function arguments and return values
- Use `Optional[T]` for nullable values
- Import types from `typing` module

Example:
```python
from typing import Optional, List

async def my_function(
    param1: str,
    param2: int = 0,
    param3: Optional[List[str]] = None
) -> bool:
    """Function docstring here."""
    pass
```

### Docstrings

Use Google-style docstrings:

```python
def function_name(arg1: str, arg2: int) -> bool:
    """Brief description of what the function does.

    More detailed description if needed.

    Args:
        arg1: Description of arg1
        arg2: Description of arg2

    Returns:
        Description of return value

    Raises:
        ValueError: When invalid input is provided
    """
    pass
```

---

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=browser_use --cov-report=html

# Run specific test file
pytest tests/test_agent.py

# Run tests matching a pattern
pytest -k "test_click"

# Run with verbose output
pytest -v
```

### Test Organization

```
tests/
├── unit/              # Unit tests (fast, isolated)
├── integration/       # Integration tests (slower, uses browser)
└── utils/            # Test utilities and helpers
```

### Writing Tests

```python
import pytest
from tests.utils import MockLLM, MockBrowserState

@pytest.mark.unit
async def test_my_feature():
    """Test description."""
    # Arrange
    mock_llm = MockLLM(responses=["test response"])

    # Act
    result = await my_function(mock_llm)

    # Assert
    assert result is not None
    assert mock_llm.call_count == 1

@pytest.mark.integration
@pytest.mark.slow
async def test_real_browser():
    """Test with real browser (marked as slow)."""
    # Test implementation
    pass
```

### Test Guidelines

- **Mark slow tests**: Use `@pytest.mark.slow` for tests taking >1s
- **Mark integration tests**: Use `@pytest.mark.integration` for tests using real browsers
- **Use fixtures**: Leverage pytest fixtures for common setup
- **Mock external services**: Mock LLM calls and external APIs
- **Test edge cases**: Include tests for error conditions

---

## Submitting Changes

### 1. Run Pre-submission Checks

```bash
# Format code
ruff format .

# Run linter
ruff check .

# Run tests
pytest

# Check test coverage
pytest --cov=browser_use --cov-report=term
```

### 2. Commit Your Changes

```bash
git add .
git commit -m "feat: add new feature X

- Implement feature X
- Add tests for feature X
- Update documentation"
```

Commit message format:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `test:` - Test additions/changes
- `refactor:` - Code refactoring
- `perf:` - Performance improvements
- `chore:` - Maintenance tasks

### 3. Push to Your Fork

```bash
git push origin feature/your-feature-name
```

### 4. Create a Pull Request

1. Go to the [browser-use repository](https://github.com/browser-use/browser-use)
2. Click "New Pull Request"
3. Select your fork and branch
4. Fill out the PR template with:
   - Clear description of changes
   - Link to related issues
   - Testing performed
   - Screenshots (if applicable)

### PR Checklist

- [ ] Tests pass locally
- [ ] New tests added for new functionality
- [ ] Documentation updated
- [ ] Code follows style guidelines
- [ ] Commits are clear and atomic
- [ ] PR description is comprehensive

---

## Review Process

### What to Expect

1. **Automated checks**: CI will run tests and quality checks
2. **Maintainer review**: A maintainer will review your code
3. **Feedback**: You may receive comments or change requests
4. **Approval**: Once approved, your PR will be merged

### Responding to Feedback

- Be responsive to comments and questions
- Make requested changes in new commits (don't force push)
- Mark conversations as resolved once addressed
- Ask for clarification if feedback is unclear

### After Merge

- Your contribution will be included in the next release
- You'll be added to the contributors list
- Thank you for making browser-use better! 🎉

---

## Additional Resources

### Communication

- **Discord**: [Join our Discord](https://link.browser-use.com/discord)
- **Issues**: [GitHub Issues](https://github.com/browser-use/browser-use/issues)
- **Discussions**: [GitHub Discussions](https://github.com/browser-use/browser-use/discussions)

### Documentation

- **Main docs**: [docs.browser-use.com](https://docs.browser-use.com)
- **Examples**: See the [examples/](examples/) directory
- **API reference**: See the [browser_use/](browser_use/) source code

### Development Tips

#### Debugging

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Use breakpoints
import pdb; pdb.set_trace()

# Save agent history for inspection
agent = Agent(
    task="...",
    llm=llm,
    save_conversation_path="debug_conversation.json"
)
```

#### Testing Locally

```bash
# Test against real websites
python examples/simple.py

# Test with different models
python examples/models/gpt-4o.py

# Test custom functions
python examples/custom-functions/save_to_file_hugging_face.py
```

#### Performance Profiling

```bash
# Profile token usage
pip install tokencost
pytest --profile

# Memory profiling
pip install memory_profiler
python -m memory_profiler your_script.py
```

---

## Special Cases

### Adding New Actions

To add a new browser action:

1. Add action model to `browser_use/controller/views.py`
2. Register action in `browser_use/controller/service.py`
3. Add tests in `tests/test_actions.py`
4. Update documentation

### Adding LLM Support

To add support for a new LLM provider:

1. Create example in `examples/models/your_provider.py`
2. Test with common tasks
3. Document any special configuration
4. Update README with supported models

### Adding Examples

To add a new example:

1. Create file in appropriate `examples/` subdirectory
2. Include clear comments and docstring
3. Add README if it's a complex example
4. Test that it works end-to-end

---

## Questions?

If you have questions that aren't answered here:

1. Check existing [Issues](https://github.com/browser-use/browser-use/issues)
2. Ask in [Discord](https://link.browser-use.com/discord)
3. Open a new issue with the `question` label

---

## License

By contributing to browser-use, you agree that your contributions will be licensed under the [MIT License](LICENSE).

---

Thank you for contributing to browser-use! Your efforts help make AI-powered browser automation accessible to everyone. 🚀
