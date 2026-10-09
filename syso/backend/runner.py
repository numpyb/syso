"""Blocking subprocess runner shared by the backend (UI uses syso/jobs for streaming)."""

from __future__ import annotations

import subprocess


class CommandError(RuntimeError):
    def __init__(self, argv: list[str], returncode: int, output: str):
        self.argv = list(argv)
        self.returncode = returncode
        self.output = output or ""
        super().__init__(
            f"command failed (exit {returncode}): {' '.join(argv)}\n---\n{self.output}"
        )


def run(argv: list[str], cwd: str | None = None) -> tuple[int, str]:
    proc = subprocess.run(argv, cwd=cwd, text=True, capture_output=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def run_ok(argv: list[str], cwd: str | None = None) -> str:
    rc, out = run(argv, cwd=cwd)
    if rc != 0:
        raise CommandError(argv, rc, out)
    return out