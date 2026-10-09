"""Bottom job/log panel: streaming output, status, progress, cancel."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from .. import jobs


class Panel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._active_job: jobs.Job | None = None
        self.running = False
        self._on_done_cb = None

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.set_margin_top(3)
        bar.set_margin_bottom(3)
        bar.set_margin_start(6)
        bar.set_margin_end(6)

        self._status = Gtk.Label(label="Idle", xalign=0.0)
        self._status.set_ellipsize(True)
        self._progress = Gtk.ProgressBar()
        self._progress.set_pulse_step(0.02)
        self._progress.set_show_text(False)
        self._progress.set_hexpand(True)
        self._cancel = Gtk.Button(label="Cancel")
        self._cancel.set_sensitive(False)
        self._cancel.connect("clicked", self._on_cancel)
        self._hide = Gtk.Button(label="Hide")
        self._hide.connect("clicked", self._on_hide)

        bar.append(self._status)
        bar.append(self._progress)
        bar.append(self._cancel)
        bar.append(self._hide)
        self.append(bar)

        self._text = Gtk.TextBuffer()
        self.view = Gtk.TextView(buffer=self._text)
        self.view.set_editable(False)
        self.view.add_css_class("monospace")
        sc = Gtk.ScrolledWindow()
        sc.set_min_content_height(150)
        sc.set_vexpand(False)
        sc.set_child(self.view)
        self.append(sc)

        # start collapsed-ish: keep visible by default
        self._last_status = "Idle"

    # ------------------------------------------------------------------
    def clear(self) -> None:
        self._text.set_text("", -1)

    def append_line(self, line: str) -> None:
        end = self._text.get_end_iter()
        self._text.insert(end, line)

    def set_status(self, text: str, percent: float | None = None) -> None:
        self._last_status = text
        self._status.set_label(text)
        if percent is None or percent < 0:
            self._progress.set_fraction(0.0)
        else:
            self._progress.set_fraction(max(0.0, min(1.0, percent / 100.0)))

    def _set_running(self, on: bool) -> None:
        self.running = on
        self._cancel.set_sensitive(on)

    # ------------------------------------------------------------------
    def run_job(self, job: jobs.Job, on_done=None) -> None:
        """Stream a Job; call on_done(job) on completion (main thread)."""
        if self.running:
            self.append_line("[syso] a job is already running — cancel or wait\n")
            return
        self._active_job = job
        self._on_done_cb = on_done
        self._set_running(True)
        self.set_status(job.label or "Running")
        job.start(on_line=self.append_line, on_done=self._job_finished)

    def run_steps(self, steps: list[list[str]], on_done=None, cwd=None) -> None:
        """Run several argv steps in a row in a background thread."""
        if self.running:
            self.append_line("[syso] a job is already running — cancel or wait\n")
            return
        self._set_running(True)
        self.set_status("Running steps")

        def worker():
            try:
                jobs.run_steps(
                    steps,
                    cwd=cwd,
                    # append_line touches a Gtk.TextBuffer: hop to main thread.
                    on_line=lambda line: GLib.idle_add(self.append_line, line),
                )
                return True, None
            except Exception as exc:  # noqa: BLE001
                return False, str(exc)

        def finished(result) -> None:
            ok, err = result
            self.set_status("Done" if ok else f"Failed: {err or 'error'}")
            self._set_running(False)
            if on_done:
                on_done(ok, err)

        t = threading.Thread(target=lambda: GLib.idle_add(finished, worker()), daemon=True)
        t.start()

    def run_task(self, fn, on_done) -> None:
        """Run arbitrary callable in a thread; on_done(result) on the main thread."""
        if self.running:
            self.append_line("[syso] a job is already running — cancel or wait\n")
            return
        self._set_running(True)
        self.set_status("Working…")

        def worker():
            try:
                return True, None, fn()
            except Exception as exc:  # noqa: BLE001
                return False, str(exc), None

        def finished(result) -> None:
            ok, err, value = result
            self.set_status("Done" if ok else f"Failed: {err or 'error'}")
            self._set_running(False)
            if on_done:
                on_done(ok, err, value)

        t = threading.Thread(target=lambda: GLib.idle_add(finished, worker()), daemon=True)
        t.start()

    # ------------------------------------------------------------------
    def _job_finished(self, job: jobs.Job) -> None:
        if job.status == "done":
            self.set_status(f"Done: {job.label}")
        elif job.status == "cancelled":
            self.set_status("Cancelled")
        else:
            tail = job.full_output.strip().splitlines()
            detail = tail[-1] if tail else "unknown error"
            self.set_status(f"Failed: {detail}")
        self._set_running(False)
        if self._on_done_cb:
            cb, self._on_done_cb = self._on_done_cb, None
            cb(job)

    def _on_cancel(self, _btn) -> None:
        if self._active_job is not None:
            self._active_job.cancel()
            self.append_line("[syso] cancel requested\n")

    def _on_hide(self, _btn) -> None:
        self.set_visible(False)

    def show_panel(self) -> None:
        self.set_visible(True)