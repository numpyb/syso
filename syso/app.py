"""Application entry point."""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk

from .window import SysoWindow


class SysoApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="io.syso.workbench",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_activate(self):
        win = self.props.active_window
        if win is None:
            win = SysoWindow(application=self)
        win.present()


def main() -> int:
    app = SysoApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())