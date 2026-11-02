FROM node:24.22.1-bookworm-slim AS engine
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY src ./src
COPY scripts/build-python.mjs ./scripts/build-python.mjs
COPY tsconfig.json tsconfig.build.json ./
COPY browser_use ./browser_use
RUN npm run build:python

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY --from=engine /build/browser_use/runtime ./browser_use/runtime
COPY browser_use ./browser_use
COPY pyproject.toml hatch_build.py README.md LICENSE ./
COPY scripts ./scripts
RUN uv sync --no-dev --no-editable
ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home browseruse && mkdir /data && chown browseruse /data
USER browseruse
WORKDIR /data
ENTRYPOINT ["browser-use"]
