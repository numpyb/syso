"""Rebuild pane: repack the working directory into a bootable ISO."""

from __future__ import annotations

import os
import shlex

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk

from ..backend import rebuild as R


class RebuildPane(Gtk.Box):
    def __init__(self, state, panel, tools, hooks=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.state = state
        self.panel = panel
        self.tools = tools
        self.hooks = hooks or {}

        self.set_margin_top(10)
        self.set_margin_bottom(10)
        self.set_margin_start(12)
        self.set_margin_end(12)

        heading = Gtk.Label(
            label="Repack the edited working directory into a bootable hybrid ISO.",
            xalign=0.0,
        )
        heading.add_css_class("dim-label")
        self.append(heading)

        grid = Gtk.Grid(column_spacing=10, row_spacing=8)

        # source
        grid.attach(self._lbl("Source ISO"), 0, 0, 1, 1)
        self._src_label = Gtk.Label(label="(none — open an ISO first)", xalign=0.0, selectable=True)
        self._src_label.set_hexpand(True)
        grid.attach(self._src_label, 1, 0, 3, 1)

        # working dir
        grid.attach(self._lbl("Working dir"), 0, 1, 1, 1)
        self._work_label = Gtk.Label(label="(not extracted yet)", xalign=0.0, selectable=True)
        self._work_label.set_hexpand(True)
        grid.attach(self._work_label, 1, 1, 3, 1)

        # destination
        grid.attach(self._lbl("Output ISO"), 0, 2, 1, 1)
        self._dest_entry = Gtk.Entry(placeholder_text="/home/me/edited.iso")
        self._dest_entry.set_hexpand(True)
        browse = Gtk.Button(label="Browse…")
        browse.connect("clicked", self._on_browse_out)
        grid.attach(self._dest_entry, 1, 2, 2, 1)
        grid.attach(browse, 3, 2, 1, 1)

        # volume label
        grid.attach(self._lbl("Volume label"), 0, 3, 1, 1)
        self._label_entry = Gtk.Entry()
        self._label_entry.set_max_length(32)
        self._label_entry.set_hexpand(True)
        self._label_entry.connect("changed", lambda *_: self._refresh_preview())
        grid.attach(self._label_entry, 1, 3, 3, 1)

        # options
        grid.attach(self._lbl("Options"), 0, 4, 1, 1)
        opts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._ck_checksum = Gtk.CheckButton(label="Embed MD5 sum (implantisomd5)")
        self._ck_checksum.set_active(True)
        self._ck_verify = Gtk.CheckButton(label="Verify with checkisomd5 afterwards")
        self._ck_verify.set_active(True)
        self._ck_hybrid = Gtk.CheckButton(label="Make isohybrid (BIOS MBR)")
        self._ck_hybrid.set_active(True)
        for c in (self._ck_checksum, self._ck_verify, self._ck_hybrid):
            c.connect("toggled", lambda *_: self._refresh_preview())
            opts.append(c)
        grid.attach(opts, 1, 4, 3, 1)

        grid.attach(self._lbl("Strategy"), 0, 5, 1, 1)
        strategy = Gtk.Label(label="xorriso −as mkisofs (structured; build only parts that exist)", xalign=0.0)
        grid.attach(strategy, 1, 5, 3, 1)

        self.append(grid)

        self._build = Gtk.Button(label="Build ISO")
        self._build.add_css_class("suggested-action")
        self._build.connect("clicked", self._on_build)
        self._build.set_sensitive(False)
        self.append(self._build)

        self._preview_buf = Gtk.TextBuffer()
        preview = Gtk.TextView(buffer=self._preview_buf)
        preview.set_editable(False)
        preview.add_css_class("monospace")
        psc = Gtk.ScrolledWindow()
        psc.set_child(preview)
        psc.set_min_content_height(150)
        expander = Gtk.Expander(label="Command preview")
        expander.set_child(psc)
        self.append(expander)

    @staticmethod
    def _lbl(text: str) -> Gtk.Label:
        l = Gtk.Label(label=text, xalign=0.0)
        l.add_css_class("dim-label")
        return l

    # ------------------------------------------------------------------
    def set_spec(self, spec) -> None:
        if spec is None:
            self._src_label.set_label("(none — open an ISO first)")
            self._build.set_sensitive(False)
            return
        self._src_label.set_label(spec.source)
        self._ck_hybrid.set_visible(spec.has_isohybrid)
        self._ck_hybrid.set_active(spec.has_isohybrid)
        if not self._label_entry.get_text():
            self._label_entry.set_text(spec.volume_id or "")
        self._refresh_preview()
        self._maybe_enable()

    def set_workdir(self, path: str) -> None:
        self._work_label.set_label(path if path else "(not extracted yet)")
        if path:
            default_out = os.path.join(
                os.path.dirname(path),
                os.path.basename(os.path.splitext(os.path.basename(path))[0])
                + "-edited.iso",
            )
            if not self._dest_entry.get_text():
                self._dest_entry.set_text(default_out)
        self._refresh_preview()
        self._maybe_enable()

    def _maybe_enable(self) -> None:
        ok = self.state.spec is not None and bool(self.state.workdir)
        self._build.set_sensitive(ok and not self.panel.running)

    # ------------------------------------------------------------------
    def _on_browse_out(self, _btn) -> None:
        dlg = Gtk.FileDialog()
        dlg.set_initial_name(os.path.basename(self._dest_entry.get_text() or "edited.iso"))
        dlg.save(self.get_root(), None, self._browse_out_cb)

    def _browse_out_cb(self, dlg, result) -> None:
        try:
            f = dlg.save_finish(result)
        except GLib.Error:
            return
        self._dest_entry.set_text(f.get_path() or "")

    # ------------------------------------------------------------------
    def _current_argv(self):
        if not (self.state.spec and self.state.workdir and self._dest_entry.get_text()):
            return None
        try:
            argv = R.rebuild_argv_xorriso(
                self.state.spec,
                self.state.workdir,
                self._dest_entry.get_text(),
                label=self._label_entry.get_text() or None,
                hybrid=(
                    self._ck_hybrid.get_active()
                    if self._ck_hybrid.get_visible()
                    else None
                ),
                tool_state=self.tools,
            )
            return argv
        except (R.RebuildError, Exception) as exc:  # noqa: BLE001
            self._preview_buf.set_text(f"# {exc}", -1)
            return None

    def _refresh_preview(self) -> None:
        argv = self._current_argv()
        if argv is None:
            return
        self._preview_buf.set_text(" " + " \\\n  ".join(shlex.quote(a) for a in argv), -1)

    # ------------------------------------------------------------------
    def _on_build(self, _btn) -> None:
        argv = self._current_argv()
        if argv is None:
            self.panel.append_line("[syso] nothing to build: open an ISO, extract it, pick an output\n")
            return
        out = self._dest_entry.get_text()
        if os.path.abspath(out) == os.path.abspath(self.state.workdir) or os.path.isdir(out):
            self.panel.append_line(f"[syso] output path must be a file outside the working dir: {out}\n")
            return

        steps = [
            argv,
        ]
        self.panel.set_status("Packaging ISO…")
        first = argv[0].rsplit("/", 1)[-1]
        self.panel.append_line(f"$ {' '.join(shlex.quote(a) for a in argv)}\n")
        if self._ck_checksum.get_active() and self.tools.tools.get("implantisomd5"):
            steps.append(R.implant_argv(out, self.tools))
        if self._ck_verify.get_active() and self.tools.tools.get("checkisomd5"):
            steps.append(R.verify_argv(out, self.tools))

        def done(ok, err) -> None:
            self._maybe_enable()
            if ok:
                dlg = Gtk.AlertDialog(
                    message="ISO rebuilt",
                    detail=f"Heading: {out}\nWrite it to a USB stick with:\n  dd if={out} of=/dev/sdX bs=4M status=progress oflag=sync",
                )
                dlg.set_buttons(["ok", "OK"])
                dlg.show(self.get_root())
            elif err:
                dlg = Gtk.AlertDialog(message="Rebuild failed", detail=err)
                dlg.show(self.get_root())

        self.panel.run_steps(steps, on_done=done)