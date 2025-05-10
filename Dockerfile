# 1. Base image
FROM python:3.11-slim

# 2. Create a non-root user (don’t switch yet)
RUN groupadd appgroup \
 && useradd -m -g appgroup appuser

# 3. Install base APT packages
RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends -qq \
      unzip libnss3 libxss1 libasound2 libx11-xcb1 \
      curl git \
 && rm -rf /var/lib/apt/lists/*

# 4. Set working directory
WORKDIR /app

# 5. Copy only dependency manifest
COPY pyproject.toml /app/

# 6. Install patchright (version from pyproject.toml)
RUN python3 -m pip install --upgrade pip --quiet \
 && python3 -m pip install patchright --quiet

# 7. Install Chromium via patchright
RUN patchright install --with-deps --no-shell chromium

# 8. Copy the rest of the codebase
COPY . /app

# 9. Install the application package
RUN python3 -m pip install . --quiet

# 10. Switch to non-root user
USER appuser

# 11. Entrypoint
ENTRYPOINT ["browser-use"]
