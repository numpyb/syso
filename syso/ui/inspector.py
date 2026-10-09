"""Inspector pane: ISO metadata + lazy in-ISO file browser (no extraction)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from .. import util
from ..backend import probe as P


class InspectorPane(Gtk.Box):
    def __init__(self, state, panel, tools):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.state = state
        self.panel = panel
        self.tools = tools
        self.set_margin_top(10)
        self.set_margin_bottom(10)
        self.set_margin_start(12)
        self.set_margin_end(12)

        heading = Gtk.Label(
            label="ISO inspector — probe a bootable disc, browse it, never modify it.",
            xalign=0.0,
        )
        heading.add_css_class("dim-label")
        self.append(heading)

        self._grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        self.append(self._grid)

        self._values: dict[str, Gtk.Label] = {}
        rows = [
            ("Source", ""),
            ("Size", ""),
            ("Volume ID", ""),
            ("Boot images", ""),
            ("Boot catalog", ""),
            ("Boot info table", ""),
            ("System area", ""),
        ]
        for i, (name, _val) in enumerate(rows):
            lbl = Gtk.Label(label=name, xalign=0.0)
            lbl.add_css_class("dim-label")
            val = Gtk.Label(label="—", xalign=0.0, selectable=True)
            val.set_wrap(True)
            self._grid.attach(lbl, 0, i, 1, 1)
            self._grid.attach(val, 1, i, 1, 1)
            self._values[name] = val

        # replay commands
        self._cmd = Gtk.TextBuffer()
        cmd_view = Gtk.TextView(buffer=self._cmd)
        cmd_view.set_editable(False)
        cmd_view.add_css_class("monospace")
        cmd_sc = Gtk.ScrolledWindow()
        cmd_sc.set_child(cmd_view)
        cmd_sc.set_min_content_height(140)
        cmd_exp = Gtk.Expander(label="xorriso replay commands (boot reproduction)")
        cmd_exp.set_child(cmd_sc)
        self.append(cmd_exp)

        tree_head = Gtk.Label(
            label="Contents (loaded from the ISO on demand)", xalign=0.0
        )
        tree_head.add_css_class("dim-label")
        self.append(tree_head)

        # TreeStore: Name, Size, IsoPath, IsDir
        self._store = Gtk.TreeStore(str, str, str, bool)
        self._tree = Gtk.TreeView(model=self._store)
        for i, title in ((0, "Name"), (1, "Size")):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)
            col.set_expand(i == 0)
            self._tree.append_column(col)
        self._tree.connect("test-expand-row", self._on_expand)
        self._tree.set_headers_visible(True)

        tv_sc = Gtk.ScrolledWindow()
        tv_sc.set_child(self._tree)
        tv_sc.set_vexpand(True)
        self.append(tv_sc)

    # ------------------------------------------------------------------
    def set_spec(self, spec: P.BootSpec | None) -> None:
        self._store.clear()
        if not spec:
            for name in self._values:
                self._values[name].set_label("—")
            self._cmd.set_text("", -1)
            return

        self._values["Source"].set_label(spec.source)
        self._values["Size"].set_label(util.human_size(spec.iso_size))
        self._values["Volume ID"].set_label(spec.volume_id or "(none)")
        self._values["Boot images"].set_label(spec.summary)
        self._values["Boot catalog"].set_label(spec.el_torito_catalog or "(none)")
        self._values["Boot info table"].set_label(
            "yes" if spec.boot_info_table else "no"
        )
        self._values["System area"].set_label(
            spec.system_area_summary or "(none)"
        )
        self._cmd.set_text(spec.el_cmd_output or "", -1)

        # top level
        try:
            nodes = P.list_dir(spec.source, "/", self.tools)
        except Exception as exc:  # noqa: BLE001
            self._store.append(None, [f"(list failed: {exc})", "", "" , False])
            return
        for node in nodes:
            self._store.append(None, self._row(node))

    @staticmethod
    def _row(node: P.IsoNode) -> tuple[str, str, str, bool]:
        size = util.human_size(node.size) if not node.is_dir else ""
        return (node.name, size, node.path, node.is_dir)

    # ------------------------------------------------------------------
    def _on_expand(self, tree, _iter, _path) -> bool:
        iso_path, is_dir = self._store[_iter][2], self._store[_iter][3]
        if not is_dir:
            return False
        if self._store.iter_n_children(_iter) > 0:
            return False
        try:
            nodes = P.list_dir(self.state.spec.source, iso_path, self.tools)
        except Exception:  # noqa: BLE001
            return False
        for node in nodes:
            self._store.append(_iter, self._row(node))
        return False