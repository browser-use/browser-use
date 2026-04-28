# Create venv and install dependencies:
uv sync

source .venv/bin/activate

# Install playwright if not already installed:
if ! python -c "import playwright" 2>/dev/null; then
    uv pip install playwright
fi

# Install Chromium if not already cached:
if [ -z "$(find ~/.cache/ms-playwright -name 'chromium-*' -maxdepth 1 2>/dev/null)" ]; then
    playwright install chromium
fi

uv pip install steel-sdk
