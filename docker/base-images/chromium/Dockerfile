ARG BASE_TAG=latest
FROM browseruse/base-system:${BASE_TAG}

WORKDIR /tmp
COPY pyproject.toml ./

# Install both playwright and patchright with versions from pyproject.toml
RUN --mount=type=cache,target=/root/.cache,sharing=locked \
    PLAYWRIGHT_VERSION=$(grep -E "playwright>=" pyproject.toml | grep -o "[0-9]\+\.[0-9]\+\.[0-9]\+" | head -1) && \
    PATCHRIGHT_VERSION=$(grep -E "patchright>=" pyproject.toml | grep -o "[0-9]\+\.[0-9]\+\.[0-9]\+" | head -1) && \
    echo "Installing playwright==$PLAYWRIGHT_VERSION patchright==$PATCHRIGHT_VERSION" && \
    pip install --no-cache-dir playwright==$PLAYWRIGHT_VERSION patchright==$PATCHRIGHT_VERSION && \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright playwright install --with-deps --no-shell chromium && \
    ln -s /opt/playwright/chromium-*/chrome-linux/chrome /usr/bin/chromium-browser && \
    chmod -R 755 /opt/playwright && \
    rm -f pyproject.toml
