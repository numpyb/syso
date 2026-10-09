"""Streaming, cancellable subprocess jobs for the UI."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading

try:
    from gi.repository import GLib
except Exception:  # pragma: no cover - headless/import-only paths
    GLib = None

_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def extract_percent(line: str) -> float | None:
    m = _PERCENT.search(line)
    return float(m.group(1)) if m else None


class Job:
    """Runs one argv list, streaming merged stdout/stderr to a callback.

    UI usage: job.start(on_line, on_done). Tests/scripts: job.run_blocking().
    """

    def __init__(self, argv: list[str], *, cwd: str | None = None, label: str = ""):
        self.argv = list(argv)
        self.cwd = cwd
        self.label = label or " ".join(argv)
        self.status = "idle"  # idle | running | done | error | cancelled
        self.returncode: int | None = None
        self.last_percent: float | None = None
        self._proc: subprocess.Popen | None = None
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._output: list[str] = []

    def _dispatch(self, callback, payload, use_idle: bool) -> None:
        if callback is None:
            return
        if use_idle and GLib is not None:
            GLib.idle_add(callback, payload)
        else:
            callback(payload)

    def cancel(self) -> None:
        self._cancel.set()
        if self._proc is not None and self._proc.poll() is None:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass  # process already gone

    # ------------------------------------------------------------------
    def run_blocking(self, on_line=None) -> int:
        self._run_loop(on_line, use_idle=False)
        return self.returncode if self.returncode is not None else -1

    def start(self, on_line=None, on_done=None) -> None:
        self._thread = threading.Thread(
            target=self._run_loop, args=(on_line, on_done, True), daemon=True
        )
        self._thread.start()

    # ------------------------------------------------------------------
    def _run_loop(self, on_line, on_done=None, use_idle: bool = False) -> None:
        self.status = "running"
        try:
            self._proc = subprocess.Popen(
                self.argv,
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except Exception as exc:  # noqa: BLE001 - surface any spawn failure
            self.status = "error"
            self.returncode = -1
            self._dispatch(
                on_line, f"[syso] failed to start: {exc}\n", use_idle
            )
            self._dispatch(on_done, self, use_idle)
            return

        assert self._proc.stdout is not None
        for raw in self._proc.stdout:
            line = raw.rstrip("\n")
            pct = extract_percent(line)
            if pct is not None:
                self.last_percent = pct
            self._output.append(line)
            self._dispatch(on_line, line + "\n", use_idle)
            if self._cancel.is_set():
                self.cancel()

        self.returncode = self._proc.wait()
        if self._cancel.is_set():
            self.status = "cancelled"
        elif self.returncode == 0:
            self.status = "done"
        else:
            self.status = "error"
        self._dispatch(on_done, self, use_idle)

    @property
    def full_output(self) -> str:
        return "\n".join(self._output)


def run_steps(steps: list[list[str]], cwd: str | None = None, on_line=None) -> int:
    """Run a sequence of argv steps; stop on first failure. Returns final rc."""
    rc = 0
    for i, argv in enumerate(steps, start=1):
        job = Job(argv, cwd=cwd, label=f"step {i}/{len(steps)}")
        if on_line:
            job.run_blocking(on_line=on_line)
        else:
            job.run_blocking()
        rc = job.returncode if job.returncode is not None else -1
        if rc != 0:
            raise RuntimeError(f"step {i} failed: {' '.join(argv)}")
    return rc