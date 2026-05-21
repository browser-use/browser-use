"""
Comet Logger — Rich-powered real-time session journal.
Every agent action is logged to console AND saved to a log file.
"""
import json
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

console = Console()


class CometLogger:
    def __init__(self, log_dir: Path | None = None):
        self.history: list[dict] = []
        self._step_count = 0
        self._log_file: Path | None = None

        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._log_file = log_dir / f"comet_{ts}.log"

    # ── Internal ──────────────────────────────────────────────

    def _record(self, level: str, message: str) -> dict:
        entry = {
            "time":    datetime.now().isoformat(),
            "level":   level,
            "message": message,
        }
        self.history.append(entry)
        if self._log_file:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    # ── Public API ────────────────────────────────────────────

    def step(self, step_num: int, message: str):
        self._step_count = step_num
        self._record("STEP", message)
        console.print(Panel(
            f"[bold cyan]Étape {step_num}[/] : {message}",
            border_style="cyan",
            padding=(0, 1),
        ))

    def thought(self, message: str):
        self._record("THOUGHT", message)
        console.print(f"  [bold yellow]🧠 Pensée   :[/] {message[:200]}")

    def action(self, tool: str, args: dict):
        msg = f"{tool}({json.dumps(args, ensure_ascii=False)[:120]})"
        self._record("ACTION", msg)
        console.print(f"  [bold green]⚙️  Action   :[/] [green]{msg}[/]")

    def observation(self, message: str):
        self._record("OBS", message)
        console.print(f"  [bold blue]👁️  Résultat :[/] {message[:300]}")

    def error(self, message: str):
        self._record("ERROR", message)
        console.print(f"  [bold red]❌ Erreur   :[/] {message}")

    def success(self, message: str):
        self._record("SUCCESS", message)
        console.print(Panel(
            f"[bold green]✅ {message}[/]",
            border_style="green",
            padding=(0, 1),
        ))

    def info(self, message: str):
        self._record("INFO", message)
        console.print(f"  [dim]ℹ️  {message}[/]")

    # ── Export ────────────────────────────────────────────────

    def get_history_text(self, last_n: int = 0) -> str:
        entries = self.history[-last_n:] if last_n else self.history
        return "\n".join(
            f"[{e['time']}] [{e['level']:8s}] {e['message']}"
            for e in entries
        )

    @property
    def log_path(self) -> str | None:
        return str(self._log_file) if self._log_file else None
