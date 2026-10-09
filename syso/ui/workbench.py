"""Workbench pane: pick a working directory, extract the ISO into it, edit files."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from .. import util
from ..backend import extract as X
from ..jobs import Job
from . import editor as editor_mod

_MONTHS = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}


def _mtime_of(info) -> str:
    try:
        dt = info.get_modification_date_time()
        if dt is not None:
            s = dt.format("%b %d %H:%M")
            if s:
                return s
    except Exception:  # noqa: BLE001
        pass
    try:
        return _mtime_str_from_timeval(info.get_modification_time())
    except Exception:  # noqa: BLE001
        return ""


def _mtime_str_from_timeval(tv) -> str:
    if getattr(tv, "tv_sec", None) is None:
        return ""
    import time

    lt = time.localtime(tv.tv_sec)
    return f"{_MONTHS[lt.tm_mon]} {lt.tm_mday:2d} {lt.tm_hour:02d}:{lt.tm_min:02d}"


def _mtime_str(p: str) -> str:
    try:
        ts = os.path.getmtime(p)
        import time

        lt = time.localtime(ts)
        return f"{_MONTHS[lt.tm_mon]} {lt.tm_mday:2d} {lt.tm_hour:02d}:{lt.tm_min:02d}"
    except OSError:
        return ""


class WorkbenchPane(Gtk.Box):
    def __init__(self, state, panel, tools, hooks=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.state = state
        self.panel = panel
        self.tools = tools
        self.hooks = hooks or {}

        self.set_margin_top(10)
        self.set_margin_bottom(10)
        self.set_margin_start(12)
        self.set_margin_end(12)

        heading = Gtk.Label(
            label="Extract the ISO to a working directory and edit files in place.",
            xalign=0.0,
        )
        heading.add_css_class("dim-label")
        self.append(heading)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._dir_entry = Gtk.Entry(placeholder_text="working directory (e.g. ~/fedora41-iso)")
        self._dir_entry.set_hexpand(True)
        browse = Gtk.Button(label="Browse…")
        browse.connect("clicked", self._on_browse_dir)
        self._extract_btn = Gtk.Button(label="Extract ISO →")
        self._extract_btn.connect("clicked", self._on_extract)
        self._extract_btn.set_sensitive(False)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", self._on_refresh)
        row.append(self._dir_entry)
        row.append(browse)
        row.append(self._extract_btn)
        row.append(refresh)
        self.append(row)

        self._tree_root: Gio.File | None = None
        self._store = Gtk.TreeStore(str, str, str, str, bool)  # name, size, mtime, disk-path(rel), is_dir
        self._tree = Gtk.TreeView(model=self._store)
        cols = [("Name", True), ("Size", False), ("Modified", False)]
        for i, (title, expand) in enumerate(cols):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)
            col.set_expand(expand)
            self._tree.append_column(col)
        self._tree.connect("test-expand-row", self._on_expand)
        self._tree.connect("row-activated", self._on_row_activated)
        self._tree.set_headers_visible(True)

        sc = Gtk.ScrolledWindow()
        sc.set_child(self._tree)
        sc.set_vexpand(True)
        self.append(sc)

        hint = Gtk.Label(
            label="Double-click a file to edit (or press Del to delete, right-click for actions).",
            xalign=0.0,
        )
        hint.add_css_class("dim-label")
        self.append(hint)

        # context menu (right-click)
        mb = Gio.Menu()
        mb.append("Open editor", "wb.open")
        mb.append("Open externally", "wb.ext")
        mb.append("Add file here…", "wb.add")
        mb.append("Reveal in file manager", "wb.reveal")
        mb.append("Delete", "wb.del")
        self._menu = Gtk.PopoverMenu(menu_model=mb)
        press = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        press.connect("pressed", self._on_right_click)
        self._tree.add_controller(press)

        self._actions = Gio.SimpleActionGroup()
        for name, cb in (
            ("open", self._act_open),
            ("ext", self._act_external),
            ("add", self._act_add),
            ("reveal", self._act_reveal),
            ("del", self._act_delete),
        ):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self._actions.add_action(a)
        self.insert_action_group("wb", self._actions)

    # ------------------------------------------------------------------
    def refresh_source(self) -> None:
        self._extract_btn.set_sensitive(self.state.source is not None)

    def _on_browse_dir(self, _btn) -> None:
        dlg = Gtk.FileDialog()
        dlg.select_folder(self.get_root(), None, self._browse_cb)

    def _browse_cb(self, dlg, result) -> None:
        try:
            f = dlg.select_folder_finish(result)
        except GLib.Error:
            return
        self.set_workdir(f.get_path())

    def set_workdir(self, path: str) -> None:
        if not path:
            return
        self.state.workdir = path
        self._dir_entry.set_text(path)
        self._tree_root = Gio.File.new_for_path(path)
        self.reload_tree()

    def _on_refresh(self, _btn) -> None:
        p = self._dir_entry.get_text()
        if p:
            self.set_workdir(p)

    def _on_extract(self, _btn) -> None:
        src: str = self.state.source
        dst = self._dir_entry.get_text().strip() or os.path.join(
            os.path.expanduser("~"), os.path.splitext(os.path.basename(src))[0] + "-work"
        )
        if os.path.exists(dst) and os.listdir(dst):
            dlg = Gtk.AlertDialog(
                message="Target working directory is not empty",
                detail=f"{dst}\nExtraction merges into it; existing files are preserved.",
            )
            dlg.set_buttons(["continue", "Continue", "cancel", "Cancel"])
            dlg.choose(self.get_root(), None, self._choose_cb, (src, dst))
            return
        self._start_extract(src, dst)

    def _choose_cb(self, dlg, result, data) -> None:
        try:
            res = dlg.choose_finish(result)
        except GLib.Error:
            return
        if res == "continue":
            self._start_extract(*data)

    def _start_extract(self, src: str, dst: str) -> None:
        os.makedirs(dst, exist_ok=True)
        job = Job(
            X.extract_full_argv(src, dst, self.tools),
            label=f"Extracting {os.path.basename(src)} → {dst}",
        )

        def done(j):
            if j.status == "done":
                self.set_workdir(dst)
                if self.hooks.get("on_extracted"):
                    self.hooks["on_extracted"](dst)
            else:
                self.panel.append_line("extraction did not complete\n")

        self.panel.run_job(job, on_done=done)

    # ------------------------------------------------------------------
    def reload_tree(self) -> None:
        self._store.clear()
        if self._tree_root is None:
            return
        for info in self._enumerate(self._tree_root):
            self._store.append(None, info)

    def _enumerate(self, gdir: Gio.File, prefix: str = "") -> list[tuple]:
        out: list[tuple] = []
        try:
            it = gdir.enumerate_children(
                "standard::name,standard::type,standard::size,time::modified",
                Gio.FileQueryInfoFlags.NONE,
                None,
            )
        except GLib.Error:
            return out
        for info in it:
            rel = os.path.join(prefix, info.get_name())
            is_dir = info.get_file_type() == Gio.FileType.DIRECTORY
            size = info.get_size() if not is_dir else 0
            mod = _mtime_of(info)
            out.append((info.get_name(), util.human_size(size) if not is_dir else "", mod, rel, is_dir))
        out.sort(key=lambda t: (not t[4], t[0].lower()))
        return out

    def _on_expand(self, tree, _iter, _path) -> bool:
        rel, is_dir = self._store[_iter][3], self._store[_iter][4]
        if not is_dir or self._store.iter_n_children(_iter) > 0:
            return False
        gdir = self._tree_root.get_child(rel) if self._tree_root else None
        for info in self._enumerate(gdir, rel):
            self._store.append(_iter, info)
        return False

    # ------------------------------------------------------------------
    def _selected(self):
        path, col = self._tree.get_cursor()
        if path is None:
            return None
        return self._store[path][3]

    # disk path for a relative tree path
    def _disk_for(self, rel: str) -> str:
        return os.path.join(self.state.workdir, rel) if self.state.workdir else rel

    def _on_row_activated(self, _tree, _path, _col) -> None:
        rel = self._selected()
        if rel is not None:
            self._open(self._disk_for(rel))

    def _open(self, disk_path: str) -> None:
        if os.path.isdir(disk_path):
            return
        if editor_mod.looks_like_text(disk_path) and os.path.getsize(disk_path) <= editor_mod.TEXT_LIMIT:
            editor_mod.open_editor_for(disk_path, self.get_root())
        else:
            self._launch(disk_path)

    def _launch(self, disk_path: str) -> None:
        try:
            Gio.AppInfo.launch_default_for_uri(
                Gio.file_new_for_path(disk_path).get_uri(), None
            )
        except GLib.Error as exc:
            self.panel.append_line(f"[syso] open failed: {exc}\n")

    # ------------------------------------------------------------------
    def _on_right_click(self, gesture, n_press, x, y) -> bool:
        path, _col = self._tree.get_path_at_pos(int(x), int(y))
        if path is not None:
            self._tree.set_cursor(path)
            rect = Gdk.Rectangle()
            rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
            self._menu.set_pointing_to(rect)
            self._menu.popup()
        return True

    def _act_open(self, *_):
        rel = self._selected()
        if rel:
            self._open(self._disk_for(rel))

    def _act_external(self, *_):
        rel = self._selected()
        if rel:
            self._launch(self._disk_for(rel))

    def _act_reveal(self, *_):
        rel = self._selected()
        base = self._disk_for(rel) if rel else self.state.workdir
        target = base if os.path.isdir(base) else os.path.dirname(base)
        self._launch(target)

    def _act_add(self, *_):
        dlg = Gtk.FileDialog()
        dlg.open(self.get_root(), None, self._add_cb)

    def _add_cb(self, dlg, result) -> None:
        try:
            src = dlg.open_finish(result)
        except GLib.Error:
            return
        rel = self._selected()
        target_dir = self._disk_for(rel) if rel and os.path.isdir(self._disk_for(rel)) else self.state.workdir
        dest = os.path.join(target_dir, src.get_basename())
        try:
            Gio.File.copy(
                src, Gio.file_new_for_path(dest), Gio.FileCopyFlags.OVERWRITE, None, None
            )
        except GLib.Error as exc:
            self.panel.append_line(f"[syso] copy failed: {exc}\n")
            return
        self.reload_tree()

    def _act_delete(self, *_):
        rel = self._selected()
        if not rel or rel == "":
            return
        disk_path = self._disk_for(rel)
        dlg = Gtk.AlertDialog(
            message=f"Delete {os.path.basename(disk_path)}?",
            detail="The file will be removed from the working directory.",
        )
        dlg.set_buttons(["delete", "Delete", "cancel", "Cancel"])
        dlg.choose(self.get_root(), None, lambda d, r, p=disk_path: self._delete_cb(d, r, p))

    def _delete_cb(self, dlg, result, disk_path: str) -> None:
        try:
            res = dlg.choose_finish(result)
        except GLib.Error:
            return
        if res != "delete":
            return
        f = Gio.File.new_for_path(disk_path)
        try:
            if not f.trash(None):
                f.delete(None)
        except GLib.Error as exc:
            self.panel.append_line(f"[syso] delete failed: {exc}\n")
            return
        self.reload_tree()