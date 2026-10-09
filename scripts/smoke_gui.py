"""GUI integration smoke test: probe -> extract (job) -> build (job) -> verify.

Drives the real widgets as a user would, then exits. Prints SMOKE OK on success.
"""

import os
import shutil
import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from syso.app import SysoApp  # noqa: E402
from syso.backend import probe as P  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISO = os.path.join(BASE, "build", "test.iso")
WORK = "/tmp/opencode/smoke_work"
OUT = os.path.join(BASE, "build", "smoke_out.iso")


class SmokeApp(SysoApp):
    def do_activate(self):
        win = self.props.active_window
        if win is None:
            win = SysoWindowSmoke(application=self)
        win.present()

    def finish(self, ok: bool, msg: str):
        print("SMOKE", "OK" if ok else "FAIL", "-", msg)
        self.quit()


from syso.window import SysoWindow  # noqa: E402


class SysoWindowSmoke(SysoWindow):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.phase = "boot"
        self.extract_started = False
        self.build_started = False
        shutil.rmtree(WORK, ignore_errors=True)
        GLib.timeout_add(400, self._open)
        GLib.timeout_add(8000, self._timeout)

    def _timeout(self):
        self.props.application.finish(False, "timed out at phase=%s running=%s" % (self.phase, self.panel.running))
        return False

    def _open(self):
        self.phase = "open"
        self._open_iso(ISO)
        return False

    def _step(self):
        if self.state.spec is None:
            print("[smoke] waiting for probe", flush=True)
            return
        if not self.extract_started:
            self.phase = "extract"
            self.extract_started = True
            print("[smoke] starting extraction", flush=True)
            self._workbench._start_extract(self.state.source, WORK)
            self.panel.append_line("\n[smoke] extraction queued\n")
            return
        if self.state.workdir is None:
            print("[smoke] waiting for extraction (running=%s)" % self.panel.running, flush=True)
            return  # extraction still running
        if not self.build_started:
            self.phase = "build"
            self.build_started = True
            print("[smoke] starting build", flush=True)
            self._rebuild._dest_entry.set_text(OUT)
            self.panel.append_line("\n[smoke] build queued\n")
            self._rebuild._on_build(None)
            return
        # build finished?
        if not self.panel.running:
            print("[smoke] build done, verifying", flush=True)
            self._verify()

    def _verify(self):
        self.phase = "verify"
        if not os.path.exists(OUT):
            self.props.application.finish(False, f"output missing: {OUT}")
            return
        spec = P.probe(OUT, self.tools)
        ok = spec.has_isohybrid and spec.bios_image and spec.efi_image
        print("output size:", os.path.getsize(OUT))
        print("rebuilt summary:", spec.summary)
        self.props.application.finish(ok, f"probed rebuilt ISO: {spec.summary}" if ok else "boot info lost")

    def poll(self, *_):
        if self.phase not in ("open", "extract", "build", "verify"):
            return True
        self._step()
        return True


# wire the poller after window construction
orig_get_child = None
import syso.window as W  # noqa: E402


def _patched_build_body(self):
    print("[smoke] building body", flush=True)
    W.SysoWindow._build_body(self)
    GLib.timeout_add(350, self.poll)
    GLib.timeout_add(900, lambda: (print("[smoke] ALIVE", flush=True), False)[1])


SysoWindowSmoke._build_body = _patched_build_body

if __name__ == "__main__":
    print("[smoke] main", flush=True)
    sys.exit(SmokeApp().run([sys.argv[0]]))