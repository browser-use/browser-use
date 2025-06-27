# Fast Dockerfile using pre-built base images
ARG REGISTRY=browseruse
ARG BASE_TAG=latest
FROM ${REGISTRY}/base-python-deps:${BASE_TAG}

LABEL name="browseruse" description="Browser automation for AI agents"

ENV BROWSERUSE_USER="browseruse" DEFAULT_PUID=911 DEFAULT_PGID=911 DATA_DIR=/data

# Create user and directories
RUN groupadd --system $BROWSERUSE_USER && \
    useradd --system --create-home --gid $BROWSERUSE_USER --groups audio,video $BROWSERUSE_USER && \
    usermod -u "$DEFAULT_PUID" "$BROWSERUSE_USER" && \
    groupmod -g "$DEFAULT_PGID" "$BROWSERUSE_USER" && \
    mkdir -p /data /home/$BROWSERUSE_USER/.config && \
    ln -s $DATA_DIR /home/$BROWSERUSE_USER/.config/browseruse && \
    mkdir -p "/home/$BROWSERUSE_USER/.config/chromium/Crash Reports/pending/" && \
    mkdir -p "$DATA_DIR/profiles/default" && \
    chown -R "$BROWSERUSE_USER:$BROWSERUSE_USER" "/home/$BROWSERUSE_USER" "$DATA_DIR"

WORKDIR /app
COPY . /app

# Install browser-use
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --all-extras --locked --no-dev --compile-bytecode

USER "$BROWSERUSE_USER"
VOLUME "$DATA_DIR"
EXPOSE 9242 9222
ENTRYPOINT ["browser-use"]
