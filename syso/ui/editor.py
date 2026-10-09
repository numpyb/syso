"""A minimal text editor window for preseed / kickstart / grub / syslinux files."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk

TEXT_LIMIT = 4 * 1024 * 1024


def looks_like_text(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
    except OSError:
        return False
    if b"\x00" in head:
        return False
    if not head:
        return True
    printable = sum(1 for b in head if 9 <= b <= 13 or 32 <= b < 127 or b >= 0x80)
    return printable / len(head) > 0.85


class EditorWindow(Gtk.Window):
    def __init__(self, path: str, parent: Gtk.Window | None = None):
        super().__init__(title=f"Edit — {os.path.basename(path)}")
        self.path = path
        self.dirty = False
        self.set_default_size(760, 560)
        if parent is not None:
            self.set_transient_for(parent)
            self.set_modal(True)

        hb = Gtk.HeaderBar()
        save = Gtk.Button(label="Save")
        save.connect("clicked", self._on_save)
        ext = Gtk.Button(label="Open external")
        ext.connect("clicked", self._on_external)
        hb.pack_start(save)
        hb.pack_start(ext)
        self.set_titlebar(hb)

        self._buffer = Gtk.TextBuffer()
        self._load()

        view = Gtk.TextView(buffer=self._buffer)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_editable(True)
        view.add_css_class("monospace")
        self._buffer.connect("modified-changed", self._on_modified)

        sc = Gtk.ScrolledWindow()
        sc.set_child(view)
        self.set_child(sc)

    # ------------------------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as exc:
            self._buffer.set_text(f"[could not read {self.path}]\n{exc}", -1)
            return
        self._buffer.set_text(text, -1)
        self._buffer.set_modified(False)

    # ------------------------------------------------------------------
    def _on_modified(self, _buf) -> None:
        self.dirty = self._buffer.get_modified()

    def _on_save(self, _btn) -> None:
        text = self._buffer.get_text(self._buffer.get_start_iter(), self._buffer.get_end_iter(), True)
        try:
            tmp = self.path + ".syso-tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, self.path)
        except OSError as exc:
            dlg = Gtk.AlertDialog(message="Save failed", detail=str(exc))
            dlg.show(self)
            return
        self._buffer.set_modified(False)

    def _on_external(self, _btn) -> None:
        try:
            Gio.AppInfo.launch_default_for_uri(
                Gio.file_new_for_path(self.path).get_uri(), None
            )
        except GLib.Error as exc:
            dlg = Gtk.AlertDialog(message="Could not open external editor", detail=str(exc))
            dlg.show(self)


def open_editor_for(path: str, parent: Gtk.Window | None = None) -> None:
    if os.path.isfile(path):
        EditorWindow(path, parent).present()