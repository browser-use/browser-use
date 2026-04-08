import json
import time
from pathlib import Path


class EventLogger:
    def __init__(self, path: str | Path, step_counter: list[int] | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Allow sharing a counter across instances, or own one
        self._counter = step_counter if step_counter is not None else [0]

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    @property
    def step(self) -> int:
        return self._counter[0]

    def log_start(self, tool: str, action: dict | None = None) -> int:
        """Log event_start and return the current step number."""
        self._write({
            "event": "event_start",
            "step": self.step,
            "tool": tool,
            "action": action or {},
            "timestamp": time.time(),
        })
        return self.step

    def log_end(self, tool: str, status: str = "success", error: str | None = None) -> int:
        """Log event_end, increment the step counter, and return the step number."""
        entry = {
            "event": "event_end",
            "step": self.step,
            "tool": tool,
            "status": status,
            "timestamp": time.time(),
        }
        if error:
            entry["error"] = error
        self._write(entry)
        self._counter[0] += 1
        return self.step

    def log(self, event: dict) -> None:
        """Write an arbitrary event dict directly."""
        self._write(event)

    def clear(self) -> None:
        """Wipe the log file and reset the step counter."""
        self.path.write_text("")
        self._counter[0] = 0

    def read_all(self) -> list[dict]:
        """Read all logged events back as a list of dicts."""
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def close(self) -> None:
        """Flush and release the file handle. Must be called before deleting the file on Windows."""
        pass  # Since we use 'a' mode (open/close per write), nothing to flush.
        # If you ever switch to a persistent file handle, close it here.
    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _write(self, entry: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    