"""Rich display utilities for Lustre CLI — spinners, status bars, and panels."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

__all__ = ["Spinner", "StatusBar", "print_step", "print_panel"]


# ---------------------------------------------------------------------------
# Spinner
# ---------------------------------------------------------------------------

class Spinner:
    """A Rich spinner widget running in a background thread.

    Usage:
        spinner = Spinner("思考中...")
        spinner.start()
        # ... do work ...
        spinner.stop()

    The spinner prints directly to stdout (overwrites one line) so it works
    even when Rich console is otherwise rendering panels/tables.
    """

    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    _instance: "Spinner | None" = None
    _lock = threading.Lock()

    def __init__(
        self,
        text: str = "处理中",
        *,
        spinner_type: str = "dots",
    ) -> None:
        self.text = text
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ---- Singleton interface (optional — for global spinner) ----

    @classmethod
    def start(cls, text: str = "处理中") -> "Spinner":
        """Start (or get existing) global spinner."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(text)
                cls._instance.start()
            else:
                cls._instance.update_text(text)
            return cls._instance

    @classmethod
    def stop(cls) -> None:
        """Stop the global spinner if running."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.stop()
                cls._instance = None

    @classmethod
    def is_active(cls) -> bool:
        with cls._lock:
            return cls._instance is not None and cls._instance._running

    # ---- Instance methods ----

    def update_text(self, text: str) -> None:
        self.text = text

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        """Background thread: prints spinner frames to stderr (no buffering)."""
        import sys
        frame_idx = 0
        while not self._stop_event.is_set():
            frame = self.SPINNER_FRAMES[frame_idx % len(self.SPINNER_FRAMES)]
            # \r = carriage return (overwrite same line), \033[K = erase to EOL
            line = f"\r{frame} {self.text}  \033[K"
            sys.stderr.write(line)
            sys.stderr.flush()
            frame_idx += 1
            # Sleep ~80ms per frame ≈ 8 fps
            for _ in range(8):
                if self._stop_event.is_set():
                    break
                time.sleep(0.01)
        # Clear the line on exit
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()


# ---------------------------------------------------------------------------
# Status Bar
# ---------------------------------------------------------------------------

class StatusBar:
    """Print a persistent status line at the bottom of the terminal.

    Overwrites the same line using \\r. Thread-safe via lock.
    """

    def __init__(self) -> None:
        self._text = ""
        self._lock = threading.Lock()

    def set(self, text: str) -> None:
        """Update the status bar text."""
        import sys
        with self._lock:
            self._text = text
            sys.stderr.write(f"\r{text:<80}\033[K\n")
            sys.stderr.flush()

    def clear(self) -> None:
        """Remove the status bar line."""
        import sys
        with self._lock:
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()


# Global status bar
_status_bar = StatusBar()


def get_status_bar() -> StatusBar:
    return _status_bar


# ---------------------------------------------------------------------------
# Convenience printers
# ---------------------------------------------------------------------------

def print_step(step: int, total: int, agent: str, description: str) -> None:
    """Print a formatted step header."""
    from rich.console import Console
    console = Console()
    ratio = f"[{step}/{total}]"
    agent_tag = f"[{agent}]"
    console.print(f"\n[bold cyan]{ratio}[/bold cyan] {agent_tag} {description}")


def print_panel(
    title: str,
    content: str,
    style: str = "gold1",
    width: int | None = None,
) -> None:
    """Print a simple Rich panel."""
    from rich.panel import Panel
    from rich.console import Console
    console = Console()
    console.print(Panel(content, title=title, border_style=style, width=width))
