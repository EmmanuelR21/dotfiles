#!/usr/bin/env python3
"""Package install popup, opened from the system popup's Install button.

Searches the official repos with `pacman -Ss` only (local sync databases, no
network, ~150ms per query). A search runs once typing pauses (debounced), and
a newer search cancels the one still running, so nothing runs while idle.

Keyboard:
  search box   type to search, Enter jumps to the first result
  results      j / Down and k / Up move, Enter installs (sudo pacman -S in
               the default terminal), R removes an installed package with
               its unneeded dependencies and config backups (sudo pacman
               -Rns), i goes back to the search box
  anywhere     Esc closes
Clicking the search box also focuses it; double-clicking a result installs it.
"""

import shlex

from gi.repository import Gio
from popup_common import (
    Gdk,
    GLib,
    Gtk,
    GtkLayerShell,
    Popup,
    label,
    run,
    run_in_terminal,
)

ACCENT = "#1793d1"
ICON_PKG = "\U000f03d6"
DEBOUNCE_MS = 300
MIN_CHARS = 2
MAX_ROWS = 60  # enough to scan; fewer widgets to build per keystroke

KEYS_DOWN = (Gdk.KEY_j, Gdk.KEY_Down)
KEYS_UP = (Gdk.KEY_k, Gdk.KEY_Up)

CSS = f"""
#panel {{ padding: 12px; min-width: 460px; }}

.logo  {{ font-size: 22px; color: {ACCENT}; min-width: 28px; }}
.title {{ font-size: 14px; }}
.sub   {{ font-size: 11px; font-weight: normal; color: #8a8f98; }}

entry {{
    min-height: 0;
    padding: 5px 8px;
    border-radius: 4px;
    border: 1px solid #3c3c3c;
    box-shadow: none;
    background-image: none;
    background-color: #151515;
    color: #ffffff;
    caret-color: {ACCENT};
}}
entry:focus {{ border-color: rgba(23, 147, 209, 0.6); }}
entry, entry text {{ font-weight: normal; }}

.results {{ background-color: #232323; border-radius: 5px; }}
list {{ background-color: transparent; padding: 4px 0; }}
list row {{ padding: 4px 10px; outline: none; border-left: 2px solid transparent; }}
list row:hover {{ background-color: #2a2a2a; }}
list row:selected {{ background-color: rgba(23, 147, 209, 0.15); border-left-color: {ACCENT}; }}
.pkg-name {{ font-size: 12px; color: #e6e6e6; }}
.pkg-ver  {{ font-size: 11px; font-weight: normal; color: #6f747d; }}
.pkg-desc {{ font-size: 11px; font-weight: normal; color: #8a8f98; }}
.pkg-tag  {{ font-size: 10px; font-weight: normal; color: #6f747d; }}
row.installed .pkg-name {{ color: #8a8f98; }}
.empty {{ font-size: 11px; font-weight: normal; color: #6f747d; padding: 2px 0; }}
.count {{ font-size: 10px; font-weight: normal; color: #6f747d; }}
.hint  {{ font-size: 10px; font-weight: normal; color: #5c6068; }}

scrollbar slider {{ min-width: 4px; border-radius: 2px; background-color: #444444; }}
scrollbar {{ background-color: transparent; border: none; }}
"""


def parse(out):
    """pacman -Ss output -> [(repo, name, version, installed, description)]."""
    pkgs = []
    for line in out.splitlines():
        if not line.startswith(" "):
            parts = line.split()
            if len(parts) < 2 or "/" not in parts[0]:
                continue
            repo, name = parts[0].split("/", 1)
            pkgs.append([repo, name, parts[1], "[installed" in line, ""])
        elif pkgs:
            pkgs[-1][4] = line.strip()
    return pkgs


class InstallPopup(Popup):
    NAME = "install"

    def __init__(self):
        super().__init__(spacing=10, align=Gtk.Align.CENTER)
        self.panel_box.set_valign(Gtk.Align.CENTER)
        self.panel_box.set_margin_top(0)
        # Typing goes straight into the search box
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        self.timer = 0
        self.cancel = None
        self.shown_query = None  # terms the listed results are for
        self.focus_results = False  # Enter was hit before results arrived

        head = Gtk.Box(spacing=10)
        head.pack_start(label(ICON_PKG, "logo", xalign=0.5), False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.pack_start(label("Install packages", "title"), False, False, 0)
        text.pack_start(label("Official repositories \u00b7 pacman", "sub"), False, False, 0)
        head.pack_start(text, True, True, 0)
        self.count = label("", "count", xalign=1)
        self.count.set_valign(Gtk.Align.END)
        head.pack_end(self.count, False, False, 0)
        self.panel.pack_start(head, False, False, 0)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Search packages\u2026")
        self.entry.connect("changed", self.on_changed)
        self.entry.connect("activate", lambda *_: self.on_enter())
        self.panel.pack_start(self.entry, False, False, 0)

        # Single click only selects; Enter or double-click installs
        self.list = Gtk.ListBox(activate_on_single_click=False)
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect("row-activated", lambda _l, row: self.install(row))
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.get_style_context().add_class("results")
        scroll.set_size_request(-1, 320)
        scroll.add(self.list)
        self.list.set_focus_vadjustment(scroll.get_vadjustment())  # keep row in view
        self.panel.pack_start(scroll, False, False, 0)

        self.panel.pack_start(
            label(
                            "Enter  results \u00b7 j/k  move \u00b7 Enter  install \u00b7 R  remove \u00b7 i  search",
                            "hint",
                            xalign=0.5,
                        ),
            False,
            False,
            0,
        )
        self.message("Type at least two letters to search")

        GLib.idle_add(self.entry.grab_focus)

    # ------------------------------------------------------------ keyboard

    def on_key(self, w, event):
        focus = self.get_focus()
        if isinstance(focus, Gtk.ListBoxRow):
            key = event.keyval
            if key in KEYS_DOWN or key in KEYS_UP:
                self.move(1 if key in KEYS_DOWN else -1)
                return True
            if key == Gdk.KEY_R:  # Shift+R
                self.remove(focus)
                return True
            if key == Gdk.KEY_i:
                self.entry.grab_focus_without_selecting()
                self.entry.set_position(-1)
                return True
        return super().on_key(w, event)  # Esc closes

    def pkg_rows(self):
        return [r for r in self.list.get_children() if getattr(r, "pkg", None)]

    def select(self, row):
        self.list.select_row(row)
        row.grab_focus()

    def move(self, step):
        rows = self.pkg_rows()
        if not rows:
            return
        cur = self.list.get_selected_row()
        i = rows.index(cur) if cur in rows else 0
        self.select(rows[max(0, min(len(rows) - 1, i + step))])

    def on_enter(self):
        terms = tuple(self.entry.get_text().split())
        if self.timer or self.cancel or terms != self.shown_query:
            self.focus_results = True  # jump once these results are in
            self.search_now()
        else:
            self.focus_first()

    def focus_first(self):
        self.focus_results = False
        rows = self.pkg_rows()
        if rows:
            self.select(rows[0])

    # ------------------------------------------------------------ search

    def clear(self):
        for child in self.list.get_children():
            child.destroy()

    def message(self, text):
        self.clear()
        row = Gtk.ListBoxRow(selectable=False, activatable=False, can_focus=False)
        row.add(label(text, "empty"))
        self.list.add(row)
        self.list.show_all()

    def on_changed(self, _entry):
        self.focus_results = False
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(DEBOUNCE_MS, self.search_now)

    def search_now(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        if self.cancel:
            self.cancel.cancel()
            self.cancel = None
        terms = self.entry.get_text().split()
        if len("".join(terms)) < MIN_CHARS:
            self.shown_query = None
            self.count.set_text("")
            self.message("Type at least two letters to search")
            return False
        try:
            proc = Gio.Subprocess.new(
                ["pacman", "-Ss", "--", *terms],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
        except GLib.Error:
            self.message("Couldn't run pacman")
            return False
        self.cancel = Gio.Cancellable()
        proc.communicate_utf8_async(None, self.cancel, self.on_done, (self.cancel, tuple(terms)))
        return False

    def on_done(self, proc, res, data):
        cancel, terms = data
        try:
            _ok, out, _err = proc.communicate_utf8_finish(res)
        except GLib.Error:  # cancelled by a newer search
            proc.force_exit()
            return
        if cancel is not self.cancel:
            return
        self.cancel = None
        self.shown_query = terms
        pkgs = parse(out or "")
        if not pkgs:
            self.count.set_text("")
            self.message("No packages found")
            return
        shown = pkgs[:MAX_ROWS]
        self.count.set_text(
            f"{len(pkgs)}" if len(pkgs) == len(shown) else f"{len(shown)} of {len(pkgs)}"
        )
        self.clear()
        for repo, name, ver, installed, desc in shown:
            row = Gtk.ListBoxRow()
            row.pkg = name
            row.installed = installed
            if installed:
                row.get_style_context().add_class("installed")
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            top = Gtk.Box(spacing=6)
            top.pack_start(label(name, "pkg-name"), False, False, 0)
            top.pack_start(label(f"{repo} \u00b7 {ver}", "pkg-ver"), False, False, 0)
            if installed:
                top.pack_end(label("installed", "pkg-tag"), False, False, 0)
            text.pack_start(top, False, False, 0)
            if desc:
                d = label(desc, "pkg-desc")
                d.set_ellipsize(3)  # Pango.EllipsizeMode.END
                d.set_tooltip_text(desc)
                text.pack_start(d, False, False, 0)
            row.add(text)
            self.list.add(row)
        self.list.show_all()
        if self.focus_results:
            self.focus_first()

    def install(self, row):
        if getattr(row, "pkg", None) and not row.installed:
            self.run_pacman("-S", row.pkg)

    def remove(self, row):
        if getattr(row, "pkg", None) and row.installed:
            self.run_pacman("-Rns", row.pkg)

    def run_pacman(self, op, pkg):
        # pacman lists what will change and asks Y/n first, so it can be cancelled
        script = (
            f"sudo pacman {op} {shlex.quote(pkg)}; "
            'printf "\\nPress Enter to close "; read -r _'
        )
        if run_in_terminal(script):
            Gtk.main_quit()

    def cleanup(self):
        if self.cancel:
            self.cancel.cancel()


if __name__ == "__main__":
    run(InstallPopup, CSS)
