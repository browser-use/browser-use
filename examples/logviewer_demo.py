import asyncio
import logging
import threading
import time
import os
import sys

# add repo root to sys.path so `browser_use` local package imports work when running the demo
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from browser_use.logging_tui import TextualLogHandler
try:
    from browser_use.ui.log_viewer import run_log_viewer
except Exception as e:  # pragma: no cover - runtime import
    raise


def main():
    q: "asyncio.Queue[dict]" = asyncio.Queue()

    # attach handler
    handler = TextualLogHandler(q)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    # run the textual UI in a thread (blocking call)
    t = threading.Thread(target=run_log_viewer, args=(q,))
    t.start()

    # emit sample logs
    for i in range(50):
        logging.info("Sample log %d", i)
        time.sleep(0.05)

    # wait for UI to close
    t.join()


if __name__ == '__main__':
    main()
