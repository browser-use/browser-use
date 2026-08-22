#!/bin/sh
# Entrypoint for the browser-use eval image.
#
# Dispatches on BU_EVAL_BROWSER:
#   local  - prewarm a headless chromium on BU_CHROME_DEBUG_PORT and hand the agent its
#            CDP url, so browser startup leaves the per-task critical path
#   cloud  - nothing to start; the agent provisions a Browser Use cloud browser
#   cdp    - nothing to start; the agent attaches to BU_CDP_URL
#
# Any arguments are passed through to eval/run_eval.py. Set BU_EVAL_CMD to run something
# else entirely (a shell, pytest, a one-off script).
set -eu

log() { printf '[entrypoint] %s\n' "$*" >&2; }

BROWSER_BACKEND="${BU_EVAL_BROWSER:-local}"
DEBUG_PORT="${BU_CHROME_DEBUG_PORT:-9222}"

prewarm_chromium() {
	CHROME="${BROWSER_USE_EXECUTABLE_PATH:-/usr/bin/chromium}"
	PROFILE_DIR="${DATA_DIR:-/data}/profiles/eval"
	mkdir -p "$PROFILE_DIR"

	log "prewarming chromium on port ${DEBUG_PORT}"
	"$CHROME" \
		--headless=new \
		--remote-debugging-port="${DEBUG_PORT}" \
		--remote-debugging-address=0.0.0.0 \
		--user-data-dir="$PROFILE_DIR" \
		--no-sandbox \
		--disable-gpu-sandbox \
		--disable-setuid-sandbox \
		--disable-dev-shm-usage \
		--no-zygote \
		--disable-background-networking \
		--disable-background-timer-throttling \
		--disable-backgrounding-occluded-windows \
		--disable-renderer-backgrounding \
		--disable-component-update \
		--disable-sync \
		--disable-search-engine-choice-screen \
		--no-first-run \
		--no-default-browser-check \
		--metrics-recording-only \
		--log-level=2 \
		about:blank &
	CHROME_PID=$!

	# Wait for CDP to answer rather than sleeping a fixed interval.
	i=0
	while [ "$i" -lt 100 ]; do
		if curl -sf "http://127.0.0.1:${DEBUG_PORT}/json/version" >/dev/null 2>&1; then
			log "chromium ready after $((i * 100))ms (pid ${CHROME_PID})"
			BU_CDP_URL="http://127.0.0.1:${DEBUG_PORT}"
			export BU_CDP_URL
			return 0
		fi
		if ! kill -0 "$CHROME_PID" 2>/dev/null; then
			log "chromium exited during startup; falling back to per-task browser launch"
			return 1
		fi
		i=$((i + 1))
		sleep 0.1
	done

	log "chromium did not expose CDP within 10s; falling back to per-task browser launch"
	kill "$CHROME_PID" 2>/dev/null || true
	return 1
}

case "$BROWSER_BACKEND" in
	local)
		if [ "${BU_PREWARM_BROWSER:-1}" = "1" ]; then
			prewarm_chromium || unset BU_CDP_URL
		else
			log "prewarm disabled; each task will launch its own chromium"
			unset BU_CDP_URL 2>/dev/null || true
		fi
		;;
	cloud)
		if [ -z "${BROWSER_USE_API_KEY:-}" ]; then
			log "ERROR: BU_EVAL_BROWSER=cloud requires BROWSER_USE_API_KEY"
			exit 1
		fi
		log "using Browser Use cloud browser"
		;;
	cdp)
		if [ -z "${BU_CDP_URL:-}" ]; then
			log "ERROR: BU_EVAL_BROWSER=cdp requires BU_CDP_URL"
			exit 1
		fi
		log "attaching to external browser at ${BU_CDP_URL}"
		;;
	*)
		log "ERROR: unknown BU_EVAL_BROWSER=${BROWSER_BACKEND} (expected local, cloud or cdp)"
		exit 1
		;;
esac

if [ -n "${BU_EVAL_CMD:-}" ]; then
	log "running: ${BU_EVAL_CMD}"
	exec sh -c "$BU_EVAL_CMD"
fi

exec python /app/eval/run_eval.py "$@"
