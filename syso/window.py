"""Main application window: state, navigation, jobs panel, header bar."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gio, Gtk

from .backend import probe as P
from .backend import tools as toolmod
from .ui.inspector import InspectorPane
from .ui.panel import Panel
from .ui.rebuildform import RebuildPane
from .ui.workbench import WorkbenchPane


class AppState:
    def __init__(self):
        self.source: str | None = None
        self.spec: P.BootSpec | None = None
        self.workdir: str | None = None


class SysoWindow(Gtk.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("syso — bootable ISO workbench")
        self.set_default_size(1060, 720)

        self.state = AppState()
        self.tools = toolmod.locate()
        self.panel = Panel()

        self._inspector = InspectorPane(self.state, self.panel, self.tools)
        self._workbench = WorkbenchPane(
            self.state, self.panel, self.tools,
            hooks={"on_extracted": self._on_extracted},
        )
        self._rebuild = RebuildPane(self.state, self.panel, self.tools)

        self._build_header()
        self._build_body()

        self._inspector.set_spec(None)
        self._check_preflight()

    # ------------------------------------------------------------------
    def _build_header(self) -> None:
        hb = Gtk.HeaderBar()
        title = Gtk.Label(label="syso")
        hb.set_title_widget(title)

        open_btn = Gtk.Button(label="Open ISO")
        open_btn.add_css_class("suggested-action")
        open_btn.connect("clicked", self._on_open)
        hb.pack_start(open_btn)

        recent_btn = Gtk.MenuButton(icon_name="document-open-recent-symbolic")
        self._recent_menu = Gio.Menu()
        recent_btn.set_menu_model(self._recent_menu)
        hb.pack_start(recent_btn)

        act = Gio.SimpleAction.new("open-recent", GLib.VariantType.new("s"))
        act.connect("activate", self._on_recent_activate)
        self.add_action(act)
        self._recent_lines: list[str] = []
        self._refresh_recent()

        hb.pack_end(self._build_theme_button())

        self.set_titlebar(hb)

    def _build_theme_button(self) -> Gtk.Widget:
        """Follow-system / light / dark preference (GTK 'gtk-color-scheme')."""
        schemes = (
            ("default", "Follow system"),
            ("prefer-light", "Light"),
            ("prefer-dark", "Dark"),
        )
        act = Gio.SimpleAction.new_stateful(
            "theme", GLib.VariantType.new("s"), GLib.Variant("s", "default")
        )
        act.connect("activate", self._on_theme)
        self.add_action(act)
        menu = Gio.Menu()
        for value, label in schemes:
            item = Gio.MenuItem.new(label, "win.theme")
            item.set_attribute_value("target", GLib.Variant("s", value))
            menu.append_item(item)
        btn = Gtk.MenuButton(icon_name="view-appearance-symbolic", tooltip_text="Theme")
        btn.set_menu_model(menu)
        return btn

    def _on_theme(self, act: Gio.SimpleAction, param: GLib.Variant) -> None:
        value = param.get_string()
        act.set_state(param)
        try:
            Gtk.Settings.get_default().set_property("gtk-color-scheme", value)
        except TypeError:
            pass  # GTK older than 4.12; system theme already follows automatically

    def _build_body(self) -> None:
        self._stack = Gtk.Stack()
        self._stack.add_named(self._inspector, "inspector")
        self._stack.add_named(self._workbench, "workbench")
        self._stack.add_named(self._rebuild, "rebuild")

        sidebar = Gtk.ListBox()
        sidebar.add_css_class("navigation-sidebar")
        rows = [("Inspector", "inspector"), ("Workbench", "workbench"), ("Rebuild", "rebuild")]
        self._row_widgets = {}
        for label, name in rows:
            r = Gtk.ListBoxRow()
            r.set_child(Gtk.Label(label=label, xalign=0.0))
            r.set_name(name)
            sidebar.append(r)
            self._row_widgets[name] = r
        sidebar.select_row(self._row_widgets["inspector"])
        sidebar.connect("row-selected", self._on_sidebar)
        sidebar.set_size_request(180, -1)
        sidebar.set_vexpand(True)

        sw = Gtk.ScrolledWindow()
        sw.set_child(sidebar)
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.append(sw)
        body.append(self._stack)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(body)
        outer.append(self.panel)
        self.set_child(outer)

    # ------------------------------------------------------------------
    def _on_sidebar(self, _listbox, row: Gtk.ListBoxRow | None) -> None:
        if row is not None:
            self._stack.set_visible_child_name(row.get_name())

    def _on_extracted(self, workdir: str) -> None:
        self._rebuild.set_workdir(workdir)
        self._stack.set_visible_child_name("rebuild")

    # ------------------------------------------------------------------
    def _on_open(self, _btn) -> None:
        dlg = Gtk.FileDialog()
        dlg.set_title("Open bootable ISO")
        f = Gtk.FileFilter()
        f.set_name("ISO images")
        f.add_pattern("*.iso")
        f.add_pattern("*.img")
        f.add_pattern("*.bin")
        dlg.set_default_filter(f)
        dlg.open(self, None, self._open_cb)

    def _open_cb(self, dlg, result) -> None:
        try:
            f = dlg.open_finish(result)
        except GLib.Error:
            return
        path = f.get_path()
        if not path:
            return
        self._open_iso(path)

    def _open_iso(self, path: str) -> None:
        self.state.source = path
        self.state.spec = None
        self.panel.set_status(f"Probing {os.path.basename(path)}…")
        self.panel.run_task(
            lambda: P.probe(path, self.tools),
            lambda ok, err, spec: self._probe_done(ok, err, spec),
        )

    def _probe_done(self, ok: bool, err: str, spec) -> None:
        if not ok:
            self.panel.append_line(f"[syso] probe failed: {err}\n")
            dlg = Gtk.AlertDialog(message="Could not read ISO", detail=err)
            dlg.show(self)
            return
        self.state.spec = spec
        self._inspector.set_spec(spec)
        self._rebuild.set_spec(spec)
        self._workbench.refresh_source()
        self.panel.append_line(
            f"[syso] {spec.source}: {spec.summary}\n"
        )
        self._remember_recent(spec.source)

    # ------------------------------------------------------------------
    def _check_preflight(self) -> None:
        if self.tools.fatal_missing:
            dlg = Gtk.AlertDialog(
                message="Missing required tools",
                detail=", ".join(self.tools.fatal_missing)
                + "\n\nInstall xorriso and osirrox (package: libisoburn / xorriso).",
            )
            dlg.show(self)
        elif self.tools.missing:
            self.panel.append_line(
                "[syso] optional tools missing: "
                + ", ".join(self.tools.missing)
                + "\n"
            )

    # ------------------------------------------------------------------
    def _recent_path(self):
        return os.path.join(GLib.get_user_config_dir(), "syso", "recent.txt")

    def _remember_recent(self, path: str) -> None:
        d = os.path.dirname(self._recent_path())
        os.makedirs(d, exist_ok=True)
        lines = []
        if os.path.exists(self._recent_path()):
            with open(self._recent_path()) as fh:
                lines = [l.strip() for l in fh if l.strip()]
        if path in lines:
            lines.remove(path)
        lines = [path] + lines[:7]
        with open(self._recent_path(), "w") as fh:
            fh.write("\n".join(lines))
        self._refresh_recent()

    def _refresh_recent(self) -> None:
        self._recent_menu.remove_all()
        lines: list[str] = []
        if os.path.exists(self._recent_path()):
            with open(self._recent_path()) as fh:
                lines = [l.strip() for l in fh if l.strip()]
        self._recent_lines = lines
        if not lines:
            item = Gio.MenuItem.new("(no recent ISOs)", None)
            self._recent_menu.append_item(item)
            return
        for i, line in enumerate(lines):
            item = Gio.MenuItem.new(os.path.basename(line), "win.open-recent")
            item.set_attribute_value("param", GLib.Variant("s", str(i)))
            self._recent_menu.append_item(item)

    def _on_recent_activate(self, _act, param) -> None:
        try:
            idx = int(param.get_string())
        except (ValueError, TypeError):
            return
        if 0 <= idx < len(self._recent_lines):
            self._open_iso(self._recent_lines[idx])